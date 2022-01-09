import asyncio, websockets, json, hmac, hashlib, base64, random, string, collections, threading

game_entryURL = "wss://live-f351468gBSWz.ws.gamesparks.net/ws/device/f351468gBSWz"

def generate_request_id():
    return f"{''.join(random.choice(string.digits) for i in range(10))}_{''.join(random.choice(string.digits) for i in range(2))}"

class ServerError(Exception): pass
class SessionTerminated(Exception): pass
class SessionEnded(Exception): pass
class SessionClosed(Exception): pass

class Client:
    def __init__(self, *, username: str, password: str, should_heartbeat = True):
        self.username = username
        self.password = password
        self.should_heartbeat = should_heartbeat
        self.ready = False
        self.manually_closed = False

        self.websocket_events = {}
        self.ready_events = []
        self.websocket_id_events = {}
        self.connect_close_events = []

    #--Decorators--

    def on_connection_close(self, function):
        '''Decorator that adds decorated function to list and calls it when client connection has closed'''
        self.connect_close_events.append(function)

        def wrapper():
            function()
        return wrapper

    def on_ready(self, function):
        '''Decorator that adds decorated function to list and calls it when client is ready.'''
        self.ready_events.append(function)

        def wrapper():
            function()
        return wrapper


    def on_websocket_recieve(self, function=None, *, class_match=None):
        '''
        Decorator that adds decorated function to list and calls it when @class matches passed argument when websocket is recieved.
        If no argument is passed the decorated function will get called every time a websocket is recieved.
        '''

        #Ran if class_match argument is not passed in
        if function != None:
            self.websocket_events.setdefault(class_match, []).append(function)

        def wrapper(func):
            #Ran if class_match argument is passed in

            self.websocket_events.setdefault(class_match, []).append(func)
            return func
        return wrapper

    #--Methods--
    def run(self):
        '''Start the websocket client'''
        self.loop = asyncio.get_event_loop()
        self.loop.create_task(self.login())
        self.loop.run_forever()
        

    def authentication_response(self, data):
        '''Update data when authentication response comes through and call on_ready'''
        
        if 'error' in data:
            raise ServerError(data['error'])

        self.auth_token = data['authToken']
        self.display_name = data['displayName']
        self.user_id = data['userId']
        self.ready = True

        for function in self.ready_events:
            if asyncio.iscoroutinefunction(function):
                asyncio.create_task(function())
            else:
                function()

    #--Coroutine Methods--

    async def close(self):
        '''Close the connection'''
        self.manually_closed = True
        await self.websocket.close()

    async def script_message(self, data):
        '''Handle incoming script data'''
        if data['extCode'] == "PLAYER_DATA_UPDATE":
            self.player_data = data['data']
        elif data['extCode'] == "UPDATE_DEALS":
            self.update_deals = data['data']
        elif data['extCode'] == "STAR_PASS_SEASON_DATA":
            self.star_pass_season_data = data['data']
        elif data['extCode'] == "CHALLENGE_EVENT_DATA":
            self.challenge_event_data = data['data']
        else:
            return

    async def websocket_listener(self):
        '''Handle websockets and call all listening functions if any'''
        while True:
            try:
                message = json.loads(await self.websocket.recv())

                if message.get('@class') == '.SessionTerminatedMessage':
                    raise SessionTerminated

                #Call all functions listening for this websocket's @class as well as functions listening for any websocket
                listening_funcs = self.websocket_events.get(message.get('@class'), [])
                general_funcs = self.websocket_events.get(None, []) #Functions listening for any traffic will be stored in key None

                for function in listening_funcs + general_funcs:
                    if (asyncio.iscoroutinefunction(function)):
                        asyncio.create_task(function(message))
                    else:
                        function(message)

                #Set object that is waiting for request with this id
                request_id = message.get('requestId')
                if request_id in self.websocket_id_events:
                    self.websocket_id_events[request_id] = message

            except websockets.exceptions.ConnectionClosed:
                for function in self.connect_close_events:
                    if asyncio.iscoroutinefunction(function):
                        asyncio.create_task(function())
                    else:
                        function()
                if self.manually_closed:
                    raise SessionClosed
                else:
                    raise SessionEnded
    
    async def heartbeat(self):
        '''Send a request every 5 seconds to keep connection alive'''
        while (True):
            await self.websocket.send(json.dumps({
                "@class": ".LogEventRequest",
                "eventKey": "GET_EVENT_POPUP",
                "requestId": generate_request_id()
            }))
            await asyncio.sleep(5)

    async def login(self):
        '''Login to golfblitz gamesparks server'''
        self.loop = asyncio.get_event_loop()
        #Get entry url
        entry_connection = await websockets.connect(game_entryURL)
        entry_info = await entry_connection.recv()

        #Connect to main websocket
        ws = await websockets.connect(json.loads(entry_info)["connectUrl"])
        response = await ws.recv()
        nonce = json.loads(response)['nonce']

        #Authenticated Connect Request
        await ws.send(json.dumps({
            "@class": ".AuthenticatedConnectRequest", 
            "hmac": base64.b64encode(hmac.new(b'a3insvuyMEertN6BV14ys1K05qcfaaoN', nonce.encode('utf-8'), hashlib.sha256).digest()).decode('utf-8'), 
            "os": "computer"
        }))
        await ws.recv()

        #Login with info
        await ws.send(json.dumps({
            "@class": ".AuthenticationRequest", 
            "userName": self.username, 
            "password": self.password, 
            "scriptData": {
                "game_version": 9999, 
                "client_version": 99999
            }, 
            "requestId": generate_request_id()
        })) 
        
        #Update self info
        self.websocket = ws

        #Make task list with websocket listener and heartbeat (if heartbeat is enabled)
        tasks = []
        
        tasks.append(asyncio.create_task(self.websocket_listener()))

        if (self.should_heartbeat):
            tasks.append(asyncio.create_task(self.heartbeat()))

        #Add authentication response function to websocket events list
        self.websocket_events.setdefault('.AuthenticationResponse', []).append(self.authentication_response)

        #Add script message function to websocket events list
        self.websocket_events.setdefault('.ScriptMessage', []).append(self.script_message)

        #Start gathered tasks
        try:
            tasks = await asyncio.gather(*tasks)
        except ServerError as exception:
            #Re throw exception if login is wrong, cancel all tasks
            [task.cancel() for task in tasks]
            raise ServerError(exception)
        except SessionTerminated as exception:
            [task.cancel() for task in tasks]
            raise SessionTerminated(exception)
        except SessionEnded as exception:
            [task.cancel() for task in tasks]
            raise SessionEnded
        except SessionClosed:
            [task.cancel() for task in tasks]

    async def list_team_chat(self):
        '''Get last 100 messages from this account's team'''

        #Generate request id for websocket listener to compare with incoming websockets
        request_id = generate_request_id()

        #Add reference of variable to websocket id events for it to get changed when response comes through
        self.websocket_id_events[request_id] = None

        #Send request
        await self.websocket.send(json.dumps({
            "@class": ".ListTeamChatRequest",
            "teamId": self.player_data['scriptData']['data']['team_id'],
            "entryCount": 100,
            "requestId": request_id
        }))

        data = None

        while True:
            data = self.websocket_id_events[request_id]
            if data != None:
                break 
            await asyncio.sleep(.1)
        return data

    async def get_player_info(self, id):
        '''Get info about a player'''

        #Generate request id for websocket listener to compare with incoming websockets
        request_id = generate_request_id()

        #Add reference of variable to websocket id events for it to get changed when response comes through
        self.websocket_id_events[request_id] = None

        #Send request
        await self.websocket.send(json.dumps({
            "@class": ".LogEventRequest",
            "eventKey": "PLAYER_INFO",
            "player_id": id,
            "requestId": request_id
        }))

        data = None

        while True:
            data = self.websocket_id_events[request_id]
            if data != None:
                break 
            await asyncio.sleep(.1)
        return data

    async def get_current_team(self):
        '''Get info about the current team the account is on'''

        #Generate request id for websocket listener to compare with incoming websockets
        request_id = generate_request_id()

        #Add reference of variable to websocket id events for it to get changed when response comes through
        self.websocket_id_events[request_id] = None

        #Send request
        await self.websocket.send(json.dumps({
            "@class": ".LogEventRequest",
            "eventKey": "GET_TEAM_REQUEST",
            "team_id": self.player_data['scriptData']['data']['team_id'],
            "requestId": request_id
        }))

        data = None

        while True:
            data = self.websocket_id_events[request_id]
            if data != None:
                break 
            await asyncio.sleep(.1)
        return data