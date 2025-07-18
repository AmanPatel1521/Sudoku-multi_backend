import random

class SudokuGenerator:
    def __init__(self, level='easy'):
        self.board = [[0 for _ in range(9)] for _ in range(9)]
        self.solution = [[0 for _ in range(9)] for _ in range(9)]
        self.level = level
        self._generate_solution()

    def _generate_solution(self):
        self.solve(self.board)
        self.solution = [row[:] for row in self.board] # Store the solved board

    def get_puzzle(self):
        puzzle = [row[:] for row in self.solution]
        # Determine number of cells to clear based on difficulty
        if self.level == 'easy':
            squares_to_remove = 40
        elif self.level == 'medium':
            squares_to_remove = 50
        elif self.level == 'hard':
            squares_to_remove = 60
        else: # expert, master, extreme
            squares_to_remove = 70

        for _ in range(squares_to_remove):
            row, col = random.randint(0, 8), random.randint(0, 8)
            while puzzle[row][col] == 0:
                row, col = random.randint(0, 8), random.randint(0, 8)
            puzzle[row][col] = 0
        return puzzle

    def get_solution(self):
        return self.solution

    def solve(self, board):
        find = self.find_empty(board)
        if not find:
            return True
        else:
            row, col = find

        nums = list(range(1, 10))
        random.shuffle(nums)

        for num in nums:
            if self.is_valid(board, num, (row, col)):
                board[row][col] = num

                if self.solve(board):
                    return True

                board[row][col] = 0
        return False

    def is_valid(self, board, num, pos):
        # Check row
        for i in range(len(board[0])):
            if board[pos[0]][i] == num and pos[1] != i:
                return False

        # Check column
        for i in range(len(board)):
            if board[i][pos[1]] == num and pos[0] != i:
                return False

        # Check box
        box_x = pos[1] // 3
        box_y = pos[0] // 3

        for i in range(box_y*3, box_y*3 + 3):
            for j in range(box_x * 3, box_x*3 + 3):
                if board[i][j] == num and (i,j) != pos:
                    return False
        return True

    def find_empty(self, board):
        for i in range(len(board)):
            for j in range(len(board[0])):
                if board[i][j] == 0:
                    return (i, j)  # row, col
        return None
