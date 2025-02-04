import requests
from fastapi import FastAPI
import fastapi
from pydantic import BaseModel
import uvicorn
import os
import signal
import logging

"""
By Todd Dole, Revision 1.1
Written for Hardin-Simmons CSCI-4332 Artificial Intelligence
Revision History
1.0 - API setup
1.1 - Very basic test player
"""

# TODO - Change the PORT and USER_NAME Values before running
DEBUG = True
PORT = 11100
USER_NAME = "nnt2204"
# TODO - change your method of saving information from the very rudimentary method here
hand = [] # list of cards in our hand
discard = [] # list of cards organized as a stack
cannot_discard = ""

# set up the FastAPI application
app = FastAPI()

# set up the API endpoints
@app.get("/")
async def root():
    ''' Root API simply confirms API is up and running.'''
    return {"status": "Running"}

# data class used to receive data from API POST
class GameInfo(BaseModel):
    game_id: str
    opponent: str
    hand: str

@app.post("/start-2p-game/")
async def start_game(game_info: GameInfo):
    ''' Game Server calls this endpoint to inform player a new game is starting. '''
    # TODO - Your code here - replace the lines below
    global hand
    global discard
    hand = game_info.hand.split(" ")
    hand.sort()
    logging.info("2p game started, hand is "+str(hand))
    return {"status": "OK"}

# data class used to receive data from API POST
class HandInfo(BaseModel):
    hand: str

@app.post("/start-2p-hand/")
async def start_hand(hand_info: HandInfo):
    ''' Game Server calls this endpoint to inform player a new hand is starting, continuing the previous game. '''
    # TODO - Your code here
    global hand
    global discard
    discard = []
    hand = hand_info.hand.split(" ")
    hand.sort()
    logging.info("2p hand started, hand is " + str(hand))
    return {"status": "OK"}

def process_events(event_text):
    ''' Shared function to process event text from various API endpoints '''
    # TODO - Your code here. Everything from here to end of function
    global hand
    global discard
    for event_line in event_text.splitlines():

        if ((USER_NAME + " draws") in event_line or (USER_NAME + " takes") in event_line):
            print("In draw, hand is "+str(hand))
            print("Drew "+event_line.split(" ")[-1])
            hand.append(event_line.split(" ")[-1])
            hand.sort()
            print("Hand is now "+str(hand))
            logging.info("Drew a "+event_line.split(" ")[-1]+", hand is now: "+str(hand))
        if ("discards" in event_line):  # add a card to discard pile
            discard.insert(0, event_line.split(" ")[-1])
        if ("takes" in event_line): # remove a card from discard pile
            discard.pop(0)
        if " Ends:" in event_line:
            print(event_line)

# data class used to receive data from API POST
class UpdateInfo(BaseModel):
    game_id: str
    event: str

@app.post("/update-2p-game/")
async def update_2p_game(update_info: UpdateInfo):
    '''
        Game Server calls this endpoint to update player on game status and other players' moves.
        Typically only called at the end of game.
    '''
    # TODO - Your code here - update this section if you want
    process_events(update_info.event)
    print(update_info.event)
    return {"status": "OK"}


@app.post("/draw/")
async def draw(update_info: UpdateInfo):
    global cannot_discard
    process_events(update_info.event)

    # Get the topmost discard card
    if discard and can_form_meld(discard[-1], hand):
        cannot_discard = discard[-1]  # Use -1 to get the most recent discard
        print(f"Checking if {cannot_discard} can form a meld with hand: {hand}")
        return {"play": "draw discard"}

    # Otherwise, draw from the stock
    print("No useful discard found. Drawing from stock.")
    cannot_discard = None
    return {"play": "draw stock"}

def get_card_value(card):
    '''Helper function to get the numeric value of a card.'''
    card_value_map = {'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}
    return card_value_map.get(card[0], int(card[0]) if card[0].isdigit() else None)

def can_form_meld(card, hand):

    value, suit = card[0], card[1]
    print(f"Checking card: {card} against hand: {hand}")

    # Check for sets
    if sum(1 for c in hand if c[0] == value) >= 2:
        print("Found a set!")
        return True

    # Check for runs (sequences in the same suit)
    # Check for runs
    same_suit_cards = sorted([c for c in hand if c[1] == suit] + [card], key=lambda c: get_card_value(c))
    values = [get_card_value(c) for c in same_suit_cards]

    print(f"Sorted values in suit {suit}: {values}")

    # Check for at least 3 consecutive values
    count = 1
    for i in range(len(values) - 1):
        if values[i + 1] - values[i] == 1:
            count += 1
            if count >= 3:  # 3 consecutive cards form a run
                print("Found a run!")
                return True
        else:
            count = 1  # Reset count if sequence is broken

    print("No meld found.")
    return False

def get_of_a_kind_count(hand):
    '''Count the number of 1 of a kind, 2 of a kind, etc. in the hand.'''
    value_counts = {}
    for card in hand:
        value = card[0]
        value_counts[value] = value_counts.get(value, 0) + 1

    of_a_kind_count = [0, 0, 0, 0]  # [1 of a kind, 2 of a kind, 3 of a kind, 4 of a kind]
    for count in value_counts.values():
        if count <= 4:
            of_a_kind_count[count - 1] += 1

    return of_a_kind_count

def get_count(hand, card):
    count = 0
    for check_card in hand:
        if check_card[0] == card[0]: count += 1
    return count

def card_value(card):
    '''Get the numeric value of a card.'''
    value = card[0]
    if value.isdigit():
        return int(value)
    return {'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}.get(value, 0)

@app.post("/lay-down/")
async def lay_down(update_info: UpdateInfo):
    '''Game Server calls this endpoint to conclude player's turn with melding and/or discard.'''
    global hand, cannot_discard

    # Process game events to update the hand and discard pile
    process_events(update_info.event)

    # Count the number of cards of each kind (e.g., 1 of a kind, 2 of a kind, etc.)
    of_a_kind_count = get_of_a_kind_count(hand)

    # Determine if we need to discard
    discard_string = ""
    if (of_a_kind_count[0] + (of_a_kind_count[1] * 2)) > 1:
        print("Need to discard")
        # Find cards that can be discarded (excluding the last drawn card)
        discard_options = [card for card in hand if card != cannot_discard]
        if discard_options:
            # Choose the highest-value card to discard
            chosen_discard = max(discard_options, key=lambda x: card_value(x))
            discard_string = f" discard {chosen_discard}"
            hand.remove(chosen_discard)  # Remove the discarded card from the hand
            print(f"Discarding {chosen_discard}. Last drawn card was {cannot_discard}")

        cannot_discard = None  # Reset the last drawn card after discarding

    # Generate melds
    play_string = ""
    hand.sort(key=lambda c: (c[0], c[1]))  # Sort hand by value and suit
    last_value = ""
    for card in hand:
        if card[0] != last_value:
            play_string += "meld "
        play_string += f"{card} "
        last_value = card[0]

    # Return the play string (melds and discard)
    return {"play": play_string.strip() + discard_string}


@app.get("/shutdown")
async def shutdown_API():
    ''' Game Server calls this endpoint to shut down the player's client after testing is completed.  Only used if DEBUG is True. '''
    os.kill(os.getpid(), signal.SIGTERM)
    logging.info("Player client shutting down...")
    return fastapi.Response(status_code=200, content='Server shutting down...')


''' Main code here - registers the player with the server via API call, and then launches the API to receive game information '''
if __name__ == "__main__":

    if (DEBUG):
        url = "http://127.0.0.1:16200/test"

        # TODO - Change logging.basicConfig if you want
        logging.basicConfig(filename="RummyPlayer.log", format='%(asctime)s - %(levelname)s - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S',level=logging.INFO)
    else:
        url = "http://127.0.0.1:16200/register"
        # TODO - Change logging.basicConfig if you want
        logging.basicConfig(filename="RummyPlayer.log", format='%(asctime)s - %(levelname)s - %(message)s',
                    datefmt='%Y-%m-%d %H:%M:%S',level=logging.WARNING)

    payload = {
        "name": USER_NAME,
        "address": "127.0.0.1",
        "port": str(PORT)
    }

    try:
        # Call the URL to register client with the game server
        response = requests.post(url, json=payload)
    except Exception as e:
        print("Failed to connect to server.  Please contact Mr. Dole.")
        exit(1)

    if response.status_code == 200:
        print("Request succeeded.")
        print("Response:", response.json())  # or response.text
    else:
        print("Request failed with status:", response.status_code)
        print("Response:", response.text)
        exit(1)

    # run the client API using uvicorn
    uvicorn.run(app, host="127.0.0.1", port=PORT)