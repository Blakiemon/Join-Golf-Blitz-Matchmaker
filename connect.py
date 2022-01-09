from websockets import auth
import golfblitz_client, asyncio, enet, sys, random

async def get_auth_token(username, password):
    #Create client
    client = golfblitz_client.Client(username=username, password=password)

    #Start and wait for it to be ready
    asyncio.create_task(client.login())

    while client.ready == False:
        #Sleep for .1 second so that it does not block the event loop
        await asyncio.sleep(.1)

    #Close client and return data
    await client.close()
    return client.auth_token, client.user_id

username = "kek"
password = "kek"
auth_token, user_id = asyncio.get_event_loop().run_until_complete(get_auth_token(username, password))

host = enet.Host(peerCount = 1)
peer = host.connect(address=enet.Address(b"35-225-183-118.noodlecakegames.net", 42775), channelCount=1)

msg = bytes.fromhex('030A18') + bytearray(user_id.encode()) + bytes.fromhex('1224') + bytearray(auth_token.encode()) + bytes.fromhex('1A046E756C6C2001')
packet = enet.Packet(data=msg, flags=enet.PACKET_FLAG_RELIABLE)

event = host.service(1000)
if event.type == enet.EVENT_TYPE_CONNECT:
    print("%s: CONNECT" % event.peer.address)

success = peer.send(0, packet)
print(success)
print("%s: OUT: %r" % (peer.address, msg))

ping = peer.ping()

while True:
    event = host.service(100)
    if event.type == enet.EVENT_TYPE_DISCONNECT:
        print("%s: DISCONNECT" % event.peer.address)
        run = False
        continue
    elif event.type == enet.EVENT_TYPE_RECEIVE:
        print("%s: IN:  %r" % (event.peer.address, event.packet.data))
        continue

