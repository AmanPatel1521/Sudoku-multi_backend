import eventlet
eventlet.monkey_patch()
from flask import Flask, request, jsonify
from flask_socketio import SocketIO, emit, join_room, leave_room
from flask_cors import CORS, cross_origin
import uuid
import random
import threading
import time

app = Flask(__name__)
CORS(app)
socketio = SocketIO(app, cors_allowed_origins="*")

from game import SudokuGenerator

rooms = {}

DIFFICULTY_TIME_LIMITS = {
    'easy': 8 * 60,
    'medium': 10 * 60,
    'hard': 15 * 60,
    'expert': 20 * 60,
    'master': 25 * 60,
    'extreme': 30 * 60,
}

class GameState:
    def __init__(self, puzzle, solution):
        self.puzzle = puzzle
        self.solution = solution
        self.current_board = [row[:] for row in puzzle]
        self.board_history = []
        self.notes_board = [[[] for _ in range(9)] for _ in range(9)]

    def to_dict(self):
        return {
            "puzzle": self.puzzle,
            "solution": self.solution,
            "current_board": self.current_board,
            "notes_board": self.notes_board
        }

class Player:
    def __init__(self, id, name):
        self.id = id
        self.name = name
        self.mistakes = 0
        self.hints_used = 0
        self.eliminated = False
        self.finished = False
        self.game_state = None
        self.score = 0
        self.sid = None

class Room:
    def __init__(self, id, host_id, puzzle, solution, difficulty):
        self.id = id
        self.players = {}
        self.host_id = host_id
        self.game_started = False
        self.game_over = False
        self.puzzle = puzzle
        self.solution = solution
        self.difficulty = difficulty
        self.time_limit = DIFFICULTY_TIME_LIMITS.get(difficulty)
        self.timer = None
        self.start_time = None

def _get_player_info(room):
    info = [
        {"player_id": p_id, "player_name": p.name, "eliminated": p.eliminated, "finished": p.finished, "score": p.score}
        for p_id, p in room.players.items()
    ]
    return sorted(info, key=lambda p: p['score'], reverse=True)

def _broadcast_player_info(room_id):
    room = rooms.get(room_id)
    if room:
        emit('current_players', {"players": _get_player_info(room)}, to=room_id)

def check_game_over(room_id):
    room = rooms.get(room_id)
    if not room or not room.game_started:
        return

    all_done = all(p.finished or p.eliminated for p in room.players.values())
    if all_done:
        if room.timer:
            room.timer.cancel()
        room.game_started = False
        room.game_over = True
        leaderboard = _get_player_info(room)
        emit('game_over', {"leaderboard": leaderboard, "message": "All players have finished!"}, to=room_id)

def end_game_by_timer(room_id):
    room = rooms.get(room_id)
    if room and room.game_started:
        room.game_started = False
        room.game_over = True
        leaderboard = _get_player_info(room)
        emit('game_over', {"leaderboard": leaderboard, "message": "Time's up!"}, to=room_id)

@app.route("/")
def index():
    return "Sudoku Multiplayer Backend is running!"

@app.route("/create_room", methods=['POST'])
@cross_origin()
def create_room():
    try:
        data = request.get_json()
        player_name = data.get('player_name')
        difficulty = data.get('difficulty', 'easy')

        if not player_name:
            return jsonify({"error": "Player name is required"}), 400

        room_id = str(uuid.uuid4())[:8]
        generator = SudokuGenerator(level=difficulty)
        puzzle = generator.get_puzzle()
        solution = generator.get_solution()

        host_player = Player(id=str(uuid.uuid4()), name=player_name)
        host_player.game_state = GameState(puzzle, solution)

        room = Room(id=room_id, host_id=host_player.id, puzzle=puzzle, solution=solution, difficulty=difficulty)
        room.players[host_player.id] = host_player
        rooms[room_id] = room

        return jsonify({
            "room_id": room_id,
            "player_id": host_player.id,
            "puzzle": puzzle,
            "solution": solution,
            "difficulty": difficulty,
            "message": "Room created successfully"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route("/join_room", methods=['POST'])
@cross_origin()
def join_room_route():
    try:
        data = request.get_json()
        room_id = data.get('room_id')
        player_name = data.get('player_name')

        if not room_id or not player_name:
            return jsonify({"error": "Room ID and player name are required"}), 400

        if room_id not in rooms:
            return jsonify({"error": "Room not found"}), 404

        room = rooms[room_id]
        if room.game_over:
            return jsonify({"error": "Game has already finished"}), 403
        if room.game_started:
            return jsonify({"error": "Game has already started"}), 403

        puzzle = room.puzzle
        solution = room.solution

        player = Player(id=str(uuid.uuid4()), name=player_name)
        player.game_state = GameState(puzzle, solution)
        room.players[player.id] = player

        return jsonify({
            "room_id": room_id,
            "player_id": player.id,
            "puzzle": puzzle,
            "solution": solution,
            "difficulty": room.difficulty,
            "message": "Joined room successfully"
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@socketio.on('join')
def on_join(data):
    room_id = data['room_id']
    player_id = data['player_id']
    join_room(room_id)

    room = rooms.get(room_id)
    if not room or player_id not in room.players:
        return

    player = room.players[player_id]
    player.sid = request.sid

    _broadcast_player_info(room_id)

@socketio.on('start_game')
def on_start_game(data):
    room_id = data['room_id']
    player_id = data['player_id']

    room = rooms.get(room_id)
    if not room or player_id != room.host_id:
        return

    if room.game_mode == 'multiplayer' and len(room.players) < 2:
        emit('error', {'message': 'You need at least two players to start the game.'}, room=request.sid)
        return

    room.game_started = True
    room.start_time = time.time()
    if room.time_limit:
        room.timer = threading.Timer(room.time_limit, end_game_by_timer, [room_id])
        room.timer.start()

    emit('game_started', {"message": "Game started!", "start_time": room.start_time}, to=room_id)

@socketio.on('move')
def on_move(data):
    room_id = data['room_id']
    player_id = data['player_id']
    r, c, value = data["row"], data["col"], data["value"]

    room = rooms.get(room_id)
    if not room or player_id not in room.players or not room.game_started:
        return

    player = room.players[player_id]
    if player.finished or player.eliminated:
        return
        
    gs = player.game_state

    gs.board_history.append([row[:] for row in gs.current_board])
    gs.current_board[r][c] = value
    gs.notes_board[r][c] = []

    is_correct = True
    if value != 0:
        if gs.solution[r][c] != value:
            is_correct = False
            player.mistakes += 1
            player.score -= 20
            if player.mistakes >= 3:
                player.eliminated = True
                emit('player_eliminated', {"player_id": player.id, "player_name": player.name}, to=room_id)
                emit('eliminated', {"message": "You have been eliminated!"}, room=request.sid)
                check_game_over(room_id)
        else:
            player.score += 50

    _broadcast_player_info(room_id)

    emit('game_state_update', {
        "game_state": gs.to_dict(),
        "mistakes": player.mistakes,
        "hints": player.hints_used,
        "score": player.score,
        "last_move": {"row": r, "col": c, "value": value, "is_correct": is_correct}
    }, room=request.sid)

    if all(all(cell != 0 for cell in row) for row in gs.current_board):
        if gs.current_board == gs.solution:
            player.finished = True
            player.finish_time = time.time() - room.start_time
            emit('player_finished', {"player_id": player.id, "player_name": player.name}, to=room_id)
            check_game_over(room_id)

@socketio.on('notes')
def on_notes(data):
    room_id = data['room_id']
    player_id = data['player_id']
    r, c, notes = data["row"], data["col"], data["notes"]

    room = rooms.get(room_id)
    if not room or player_id not in room.players:
        return

    player = room.players[player_id]
    gs = player.game_state

    gs.notes_board[r][c] = notes
    emit('game_state_update', {
        "game_state": gs.to_dict(),
        "mistakes": player.mistakes,
        "hints": player.hints_used,
        "score": player.score
    }, room=request.sid)

@socketio.on('undo')
def on_undo(data):
    room_id = data['room_id']
    player_id = data['player_id']

    room = rooms.get(room_id)
    if not room or player_id not in room.players:
        return

    player = room.players[player_id]
    gs = player.game_state

    if gs.board_history:
        gs.current_board = gs.board_history.pop()
        emit('game_state_update', {
            "game_state": gs.to_dict(),
            "mistakes": player.mistakes,
            "hints": player.hints_used,
            "score": player.score
        }, room=request.sid)
    else:
        emit('error', {"message": "Nothing to undo!"}, room=request.sid)

@socketio.on('hint')
def on_hint(data):
    room_id = data['room_id']
    player_id = data['player_id']

    room = rooms.get(room_id)
    if not room or player_id not in room.players:
        return

    player = room.players[player_id]
    gs = player.game_state

    if player.hints_used < 3:
        empty_cells = [(r, c) for r in range(9) for c in range(9) if gs.current_board[r][c] == 0]
        if empty_cells:
            r, c = random.choice(empty_cells)
            hint_value = gs.solution[r][c]
            gs.current_board[r][c] = hint_value
            player.hints_used += 1
            player.score += 25

            _broadcast_player_info(room_id)

            emit('hint_given', {"row": r, "col": c, "value": hint_value, "hints_used": player.hints_used, "score": player.score}, room=request.sid)
            emit('game_state_update', {"game_state": gs.to_dict(), "mistakes": player.mistakes, "hints": player.hints_used, "score": player.score}, room=request.sid)
        else:
            emit('error', {"message": "No empty cells for a hint!"}, room=request.sid)
    else:
        emit('error', {"message": "No hints left!"}, room=request.sid)

@socketio.on('disconnect')
def on_disconnect():
    player_to_remove = None
    room_of_player = None
    
    for room in rooms.values():
        for p_id, p in room.players.items():
            if p.sid == request.sid:
                player_to_remove = p
                room_of_player = room
                break
        if player_to_remove:
            break

    if player_to_remove and room_of_player:
        player_id = player_to_remove.id
        player_name = player_to_remove.name
        
        del room_of_player.players[player_id]
        
        leave_room(room_of_player.id)
        
        emit('player_left', {"player_id": player_id, "player_name": player_name}, to=room_of_player.id)
        
        _broadcast_player_info(room_of_player.id)
        
        if room_of_player.game_started and len(room_of_player.players) > 0:
            check_game_over(room_of_player.id)
        elif len(room_of_player.players) == 0:
            if room_of_player.timer:
                room_of_player.timer.cancel()
            if room_of_player.id in rooms:
                del rooms[room_of_player.id]

if __name__ == '__main__':
    socketio.run(app, debug=True)
