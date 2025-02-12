import requests
from fastapi import FastAPI, Response
from pydantic import BaseModel
import uvicorn
import os
import signal
import logging
import math, random, copy

# -------------------- GLOBAL CONFIGURATION --------------------

DEBUG = True
PORT = 11101
USER_NAME = "nakai"

# Global game state variables:
hand = []              # list of cards in our hand
discard = []           # list of cards organized as a stack
cannot_discard = ""
last_picked_card = ""

#Globals to track opponent information.
opponent_name = None
opponent_discard_picks = []  # list of cards the opponent has picked from discard

"""
This dictionary tracks the history of hands played.
"""
game_history = {
    "hands_played": 0,
    "hands_won":0,
    "total_score":0,
    "hand_details": []
}

#These parameters are used in the evaluation function and adjusted over time
learning_weights ={
    "meld_bonus":10,        #Bonus for making a meld
    "discard_penalty":1     #penalty multiplier for deadwood
}
# -------------------- FASTAPI SETUP --------------------

app = FastAPI()

@app.get("/")
async def root():
    return {"status": "Running"}

# Model for starting the game.
class GameInfo(BaseModel):
    game_id: str
    opponent: str
    hand: str

# Model for starting a new hand.
class HandInfo(BaseModel):
    hand: str

# New model for update endpoints (/draw/, /update-2p-game/, /lay-down/).
class UpdateInfo(BaseModel):
    game_id: str
    event: str

@app.post("/start-2p-game/")
async def start_game(game_info: GameInfo):
    global hand, opponent_name, discard
    hand = game_info.hand.split(" ")
    hand.sort()
    opponent_name = game_info.opponent   # Store the opponent's name.
    discard = []
    logging.info("2p game started, hand is " + str(hand) + ", opponent: " + opponent_name)
    return {"status": "OK"}



@app.post("/start-2p-hand/")
async def start_hand(hand_info: HandInfo):
    global hand, discard
    discard = []
    hand = hand_info.hand.split(" ")
    hand.sort()
    logging.info("2p hand started, hand is " + str(hand))
    return {"status": "OK"}

# -------------------- EVENT PROCESSING --------------------

def process_events(event_text):
    """
    Process event text from the game server. Also records which cards the opponent takes from the discard.
    """
    global hand, discard, opponent_discard_picks, opponent_name
    for event_line in event_text.splitlines():
        # When we draw or take a card, add it to our hand.
        if ((USER_NAME + " draws") in event_line or (USER_NAME + " takes") in event_line):
            print("In draw, hand is " + str(hand))
            print("Drew " + event_line.split(" ")[-1])
            drawn_card = event_line.split(" ")[-1]
            logging.info("Drew " + drawn_card + ", hand before: " + str(hand))
            hand.append(drawn_card)
            hand.sort()
            print("Hand is now " + str(hand))
            logging.info("Hand is now: " + str(hand))
        # When any player discards, add the card to the discard pile.
        if "discards" in event_line:
            card = event_line.split(" ")[-1]
            discard.insert(0, card)
        # When a card is taken from discard:
        if "takes" in event_line:
            # Record if the opponent took a card.
            if opponent_name and opponent_name in event_line:
                taken_card = event_line.split(" ")[-1]
                opponent_discard_picks.append(taken_card)
                logging.info("Opponent took " + taken_card + " from discard.")
            if discard:
                discard.pop(0)
        if " Ends:" in event_line:
            logging.info(event_line)
            print(event_line)

# -------------------- HELPER FUNCTIONS --------------------

def get_card_value(card):
    card_value_map = {'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}
    return card_value_map.get(card[0], int(card[0]) if card[0].isdigit() else None)

def card_value(card):
    value = card[0]
    if value.isdigit():
        return int(value)
    return {'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}.get(value, 0)

def get_valid_melds(cards):
    """
    Returns a list of candidate melds from the given list of cards.
    A meld is either a set (3+ of the same rank) or a run (3+ consecutive cards in the same suit).
    """
    melds = []
    # Check for sets.
    rank_dict = {}
    for card in cards:
        rank_dict.setdefault(card[0], []).append(card)
    for rank, same_rank in rank_dict.items():
        if len(same_rank) >= 3:
            melds.append(sorted(same_rank))
    # Check for runs.
    suit_dict = {}
    for card in cards:
        suit_dict.setdefault(card[1], []).append(card)
    for suit, suit_cards in suit_dict.items():
        sorted_cards = sorted(suit_cards, key=lambda c: card_value(c))
        seq = [sorted_cards[0]]
        for i in range(1, len(sorted_cards)):
            if card_value(sorted_cards[i]) == card_value(seq[-1]) + 1:
                seq.append(sorted_cards[i])
            else:
                if len(seq) >= 3:
                    melds.append(seq.copy())
                seq = [sorted_cards[i]]
        if len(seq) >= 3:
            melds.append(seq.copy())
    return melds

# -------------------- MCTS LOGIC --------------------

def copy_state(state):
    """
    Creates a deep copy of the game state.
    """
    return {
        "remaining": state["remaining"].copy(),
        "melds": copy.deepcopy(state["melds"]),
        "discard": state["discard"],
        "finished": state["finished"]
    }


def get_possible_moves(state):
    """
    Returns a list of possible moves from the given state.
    """
    if state["finished"]:
        return []
    moves = []
    valid_melds = get_valid_melds(state["remaining"])
    for meld in valid_melds:
        if all(card in state["remaining"] for card in meld):
            moves.append(("meld", meld))
    if state["remaining"]:
        for card in state["remaining"]:
            moves.append(("finish", card))
    return moves

def apply_move(state, move):
    """
    Applies a move to the given state and returns the new state.
    """
    new_state = copy_state(state)
    if move[0] == "meld":
        meld = move[1]
        for card in meld:
            if card in new_state["remaining"]:
                new_state["remaining"].remove(card)
        new_state["melds"].append(meld)
        new_state["finished"] = False
    elif move[0] == "finish":
        card = move[1]
        if card in new_state["remaining"]:
            new_state["remaining"].remove(card)
        new_state["discard"] = card
        new_state["finished"] = True
    return new_state

def evaluate_state(state):
    """
    Evaluates the given state and returns a score.
    """
    if not state["finished"]:
        raise ValueError("Tried to evaluate a nonterminal state")
    deadwood = sum(card_value(c) for c in state["remaining"])
    if deadwood == 0:
        return 100  # Bonus for going gin!
    return -deadwood

def simulate(state):
    """
    Simulates a random game from the given state and returns the final score.
    """
    current_state = copy_state(state)
    while not current_state["finished"]:
        moves = get_possible_moves(current_state)
        if not moves:
            if current_state["remaining"]:
                move = ("finish", random.choice(current_state["remaining"]))
            else:
                break
        else:
            move = random.choice(moves)
        current_state = apply_move(current_state, move)
    try:
        return evaluate_state(current_state)
    except ValueError:
        return -1000

class MCTSNode:
    """
    A node in the MCTS tree.
    state: The game state at this node.
    parent: The parent node(the state from which this state was reached).
    move: The move that led from the parent node to this node.
    children: The child nodes (states reachable from this state or that have been expanded from this node).
    untried_moves: The moves that have not been explored from this state.
    visits: The number of times this node has been visited.
    total_reward: The total reward received from this node.
    """
    def __init__(self, state, parent=None, move=None):
        self.state = state
        self.parent = parent
        self.move = move  # The move that led to this state.
        self.children = []
        self.untried_moves = get_possible_moves(state)
        self.visits = 0
        self.total_reward = 0.0

def is_terminal(state):
    return state["finished"]

def select_child(node):
    C = 1.41
    return max(
        node.children,
        key=lambda c: c.total_reward / c.visits + C * math.sqrt(2 * math.log(node.visits) / c.visits)
    )

def mcts(root_state, iterations=1000):
    root = MCTSNode(root_state)
    for i in range(iterations):
        node = root
        # Selection:
        while node.untried_moves == [] and not is_terminal(node.state):
            node = select_child(node)
        # Expansion:
        if node.untried_moves:
            move = random.choice(node.untried_moves)
            new_state = apply_move(node.state, move)
            child = MCTSNode(new_state, parent=node, move=move)
            node.children.append(child)
            node.untried_moves.remove(move)
            node = child
        # Simulation:
        reward = simulate(node.state)
        # Backpropagation:
        while node is not None:
            node.visits += 1
            node.total_reward += reward
            node = node.parent
    return root

def get_best_sequence(root):
    """
    Returns the sequence of moves that leads to the best child node.
    """
    sequence = []
    node = root
    while node.children:
        node = max(node.children, key=lambda c: c.visits)
        if node.move is not None:
            sequence.append(node.move)
    return sequence

def simulate_sequence(state, sequence):
    s = copy_state(state)
    for move in sequence:
        s = apply_move(s, move)
    return s

def build_play_string(final_state):
    play_string = ""
    for meld in final_state["melds"]:
        play_string += "meld " + " ".join(meld) + " "
    if final_state["finished"] and final_state["discard"]:
        play_string += "discard " + final_state["discard"]
    return play_string.strip()

def update_game_history(hand_result, score):
    """
    A-2: Update the global game_history with the result of a hand.
    hand_result: A string or dict describing the outcome of the hand.
    score: Numeric score (positive for win, negative for loss).
    """
    global game_history
    game_history["hands_played"] += 1
    game_history["total_score"] += score
    if score > 0:  # Assume positive score means a win.
        game_history["hands_won"] += 1
    game_history["hand_details"].append({
        "result": hand_result,
        "score": score
    })
    logging.info("Updated game history: " + str(game_history))

def update_learning_weights(hand_score):
    """
    A-3: Adjust learning weights based on hand outcome.
    For example, if the hand score was very negative, increase the discard penalty.
    """
    global learning_weights
    if hand_score < -20:
        learning_weights["discard_penalty"] += 0.1
    elif hand_score > 20:
        learning_weights["meld_bonus"] += 0.5
    logging.info("Updated learning weights: " + str(learning_weights))



# -------------------- ENDPOINTS --------------------

@app.post("/draw/")
async def draw(update_info: UpdateInfo):
    """
    Draw from the discard if it can form a meld with our hand.
    Otherwise, draw from the stock.
    """
    try:
        global cannot_discard, last_picked_card
        process_events(update_info.event)
        discard_card = discard[0] if discard else None
        last_picked_card = None
        if discard and can_form_meld(discard[0], hand):
            cannot_discard = discard[0]
            last_picked_card = discard[0]
            logging.info(f"Drawing discard {discard[0]} because it can form a meld with hand: {hand}")
            print("Drawing discard", discard[0])
            return {"play": "draw discard"}
        logging.info("No useful discard found. Drawing from stock.")
        cannot_discard = None
        last_picked_card = None
        print("Drawing from stock.")
        return {"play": "draw stock"}
    except Exception as e:
        logging.error("Error in draw endpoint: " + str(e))
        return Response("Error in draw", status_code=500)

def can_form_meld(card, hand_list):
    """
    Check if the given card can form a meld with the given hand.
    A meld is either a set (3+ of the same rank) or a run (3+ consecutive cards in the same suit).
    """
    value, suit = card[0], card[1]
    if sum(1 for c in hand_list if c[0] == value) >= 2:
        return True
    same_suit_cards = sorted([c for c in hand_list if c[1] == suit] + [card], key=lambda c: get_card_value(c))
    values = [get_card_value(c) for c in same_suit_cards]
    count = 1
    for i in range(len(values)-1):
        if values[i+1] - values[i] == 1:
            count += 1
            if count >= 3:
                return True
        else:
            count = 1
    return False

@app.post("/lay-down/")
async def lay_down(update_info: UpdateInfo):
    """
    Game Server calls this endpoint to conclude player's turn with melding and/or discard.
    """
    try:
        global hand
        process_events(update_info.event)
        print("Starting lay-down with hand:", hand)
        logging.info("Starting lay-down with hand: " + str(hand))
        root_state = {
            "remaining": hand.copy(),
            "melds": [],
            "discard": None,
            "finished": False
        }
        root = mcts(root_state, iterations=1000)
        best_sequence = get_best_sequence(root)
        final_state = simulate_sequence(root_state, best_sequence)
        play_string = build_play_string(final_state)
        logging.info("MCTS chose play: " + play_string)
        print("MCTS play string:", play_string)
        # Update our global hand by removing melded and discarded cards.
        meld_cards = [card for meld in final_state["melds"] for card in meld]
        for card in meld_cards:
            if card in hand:
                hand.remove(card)
        if final_state["finished"] and final_state["discard"] in hand:
            hand.remove(final_state["discard"])
        return {"play": play_string}
    except Exception as e:
        logging.error("Error in lay-down endpoint: " + str(e))
        return Response("Error in lay-down", status_code=500)

@app.post("/update-2p-game/")
async def update_2p_game(update_info: UpdateInfo):
    try:
        process_events(update_info.event)
        logging.info("Game update: " + update_info.event)
        # If the event indicates the end of a hand, update game history and learning.
        if " Ends:" in update_info.event:
            # For demonstration, we derive a hand score using the current evaluation
            # (In practice, you may extract a score from the event details.)
            current_state = {
                "remaining": hand.copy(),
                "melds": [],
                "discard": None,
                "finished": True
            }
            try:
                hand_score = evaluate_state(current_state)
            except Exception:
                hand_score = -1000
            update_game_history(update_info.event, hand_score)
            update_learning_weights(hand_score)
        return {"status": "OK"}
    except Exception as e:
        logging.error("Error in update-2p-game endpoint: " + str(e))
        return Response("Error in update-2p-game", status_code=500)

@app.get("/shutdown")
async def shutdown_API():
    os.kill(os.getpid(), signal.SIGTERM)
    logging.info("Player client shutting down...")
    return Response(status_code=200, content='Server shutting down...')

# -------------------- MAIN --------------------

if __name__ == "__main__":
    if DEBUG:
        url = "http://127.0.0.1:16200/test"
        logging.basicConfig(filename="RummyPlayer.log",
                            format='%(asctime)s - %(levelname)s - %(message)s',
                            datefmt='%Y-%m-%d %H:%M:%S',
                            level=logging.INFO)
    else:
        url = "http://127.0.0.1:16200/register"
        logging.basicConfig(filename="RummyPlayer.log",
                            format='%(asctime)s - %(levelname)s - %(message)s',
                            datefmt='%Y-%m-%d %H:%M:%S',
                            level=logging.WARNING)
    payload = {
        "name": USER_NAME,
        "address": "127.0.0.1",
        "port": str(PORT)
    }
    try:
        response = requests.post(url, json=payload)
    except Exception as e:
        print("Failed to connect to server.  Please contact Mr. Dole.")
        exit(1)
    if response.status_code == 200:
        print("Request succeeded.")
        print("Response:", response.json())
    else:
        print("Request failed with status:", response.status_code)
        print("Response:", response.text)
        exit(1)
    uvicorn.run(app, host="127.0.0.1", port=PORT)
