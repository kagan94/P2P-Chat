#! /usr/bin/env python
# -*- coding: utf-8 -*-

# Imports----------------------------------------------------------------------
import ConfigParser as CP
import threading
from argparse import ArgumentParser  # Parsing command line arguments
from datetime import datetime
from socket import *
from socket import error as socket_error
import time
import select

# Local files
from gui import *
from common import *


# Path to the config file
current_path = os.path.abspath(os.path.dirname(__file__))
config_file = os.path.join(current_path, "config.ini")

global_lock = threading.Lock()


# Main Client handler ==================================================================================
class ClientSession(threading.Thread):
    def __init__(self, client_sock, server, i_am_server=False):
        if not i_am_server:
            threading.Thread.__init__(self)

        self.client_sock = client_sock
        self.server = server  # Server object

        # Extra info about this session
        self.user_id = None
        self.nickname = None

        self.i_am_server = i_am_server

    def process_command(self, msg):
        ''' Main msg handler '''

        username, command, data = parse_query(msg)
        user_id = self.user_id
        resp_code = RESP.OK

        print ">> Received command: %s, data: %s" % (command_to_str(command), data[:15])

        # Check that user_id is legal and we can use it later
        if command not in [COMMAND.REG_NICKNAME, COMMAND.NOTIFY_ABOUT_USER_ID] and self.user_id is None:
            print "Error user_id"
            resp_code, data = RESP.FAIL, ""

        elif command == COMMAND.REG_NICKNAME:
            nickname = data
            resp_code, data, user_id = self.server.reg_nickname(nickname)
            if resp_code == RESP.OK:
                self.user_id = user_id
                self.nickname = nickname

        elif command == COMMAND.NOTIFY_ABOUT_USER_ID:
            user_id, nickname = parse_data(data)

            self.server.save_client_presence(user_id, nickname)

        elif command == COMMAND.I_AM_ONLINE:
            resp_code, data = self.server.i_am_online(user_id, username)

        elif command == COMMAND.I_AM_OFFLINE:
            resp_code, data = self.server.i_am_offline(user_id, username)

        elif command == COMMAND.SEND_MSG:
            msg_time, chat_id, msg = parse_data(data)
            resp_code, data = self.server.send_msg(user_id, username, msg_time, chat_id, msg)

        elif command == COMMAND.ALL_MSGS:
            resp_code, data = self.server.all_msg(user_id, chat_id=data)

        elif command == COMMAND.LEAVE_CHAT:
            resp_code, data = self.server.leave_chat(user_id, chat_id=data)

        elif command == COMMAND.CREATE_CHAT:
            print parse_data(data)
            chat_name, chat_type, invited_users = parse_data(data)
            resp_code, data = self.server.create_chat(user_id, username, chat_name, chat_type, invited_users)

        elif command == COMMAND.JOIN_CHAT:
            resp_code, data = self.server.join_chat(user_id, username, chat_name=data)

        elif command == COMMAND.CHATS_LIST:
            resp_code, data = self.server.chats_list(user_id)

        elif command == COMMAND.CHAT_PARTICIPANTS:
            resp_code, data = self.server.chat_participants(user_id, chat_id=data)

        elif command == COMMAND.ALL_USERS:
            resp_code, data = self.server.all_users(user_id)

        query = pack_resp(command, resp_code, data)
        return query

    def run(self, master=None):
        current_thread = threading.current_thread()
        connection_n = current_thread.getName().split("-")[1]
        current_thread.socket = self.client_sock

        LOG.debug("Client %s connected:" % connection_n)
        LOG.debug("Client's socket info : %s:%d:" % self.client_sock.getsockname())

        while True:
            msg = tcp_receive(self.client_sock)

            # In case some errors with connection
            if msg is None:
                LOG.debug("Client(%s) closed the connection" % connection_n)
                break

            # Main msg worker
            query = self.process_command(msg)

            # Send response on requested command
            res = tcp_send(self.client_sock, query)

            # Case: some problem with receiving data
            if not res:
                LOG.debug("Client(%s, %s) closed the connection" % self.client_sock.getsockname())
                break

        # Close TCP Client socket before exit
        if self.client_sock:
            close_socket(self.client_sock, "Close client socket - #%s." % connection_n)


class Main_Server(object):
    def __init__(self, master=None):
        self.tcp_sock = None
        self.sessions = []
        self.notifications = {}  # in format <user_id>: notification_query

        self.master = master  # he should be a client object if this peer is master
        self.lock = threading.Lock()

        ##############################
        # To store users, msgs, chats:
        # format {<user_id>: {
        #   "name": user_name,
        #   "status": <ONLINE / OFFLINE>
        # }}
        self.users = {}

        # format {<chat_id (int)>: {
        #   "name": chat_name,
        #   "type": <PUBLIC / PRIVATE>,
        #   "participants_ids": (list),
        #   "owner_id": (int)
        # }}
        self.chats = {}

        # format {<chat_id (int)>: [
        # {
        #   "time_created": timestamp,  - strftime("%Y-%m-%d %H:%M:%S")
        #   "author_id": (int),
        #   "msg": (str),  # user's message
        # }, {...}, ..
        # ]}
        self.msgs = {}

        self.last_user_id = 1
        self.last_chat_id = 1

        test = False
        if test:
            # Pseudo chats
            self.chats[1] = {
                "name": "public chat",
                "type": PUBLIC,
                "participants_ids": [],
                "owner_id": None
            }
            self.chats[2] = {
                "name": "private chat",
                "type": PRIVATE,
                "participants_ids": [],
                "owner_id": None
            }
            self.last_chat_id = 3

            # Pseudo users
            self.users[1] = {
                "name": "user 1",
                "status": ONLINE
            }
            self.users[2] = {
                "name": "user 2",
                "status": OFFLINE
            }
            self.users[3] = {
                "name": "user 3",
                "status": ONLINE
            }
            self.last_user_id = 4

    def do_broadcast(self, udp_sock, broadcast_port):
        # Send chosen host and port to client through UDP Broadcast
        # that client may establish TCP connection
        msg = "server_online"

        # Server does broadcasting msg each 0.1 second
        while True:
            udp_sock.sendto(msg, ('<broadcast>', broadcast_port))
            time.sleep(0.1)

        # Close UDP socket before exit
        if udp_sock:
            close_socket(udp_sock, "Close client socket.")

    ###################
    # Main function to run server ============================================================
    ###################
    def main_loop(self, udp_broadcast_port, global_lock):
        ''' Main server loop. There server accepts clients and collect them into the session queue '''
        print "####################"
        print "Server is running"

        self.global_lock = global_lock

        udp_sock = socket(AF_INET, SOCK_DGRAM)
        udp_sock.bind(('', 0))  # bind udp socket to any free port
        udp_sock.setsockopt(SOL_SOCKET, SO_BROADCAST, 1)

        # Binding the TCP/IP socket
        host, port = udp_sock.getsockname()
        self.tcp_sock = socket(AF_INET, SOCK_STREAM)

        try:
            self.tcp_sock.bind((host, port))
        except socket_error as (code, msg):
            if code == 10048:
                LOG.error("Server already started working... (TCP binding error)")
            return

        # Use new async Thread to do broadcasting msg (over UDP) that server is online now
        threading.Thread(target=self.do_broadcast, args=(udp_sock, udp_broadcast_port,)).start()

        # Socket in the listening state
        LOG.info("Waiting for a client connection...")

        # If we want to limit # of connections, then change 0 to # of possible connections
        self.tcp_sock.listen(0)
        print 'TCP Socket created, bound to %s:%d, and in listening state now' % self.tcp_sock.getsockname()

        while True:
            try:
                # Client connected
                client_socket, addr = self.tcp_sock.accept()
                LOG.debug("New Client connected.")

                session = ClientSession(client_socket, server=self)
                self.sessions.append(session)
                session.start()

            except KeyboardInterrupt:
                LOG.info("Terminating by keyboard interrupt...")
                break
            except socket_error as err:
                LOG.error("Socket error - %s" % err)

        # Terminating application
        if self.tcp_sock:
            close_socket(self.tcp_sock, "Close client socket (in notif. thread).")

    ###################
    # Notifications methods ===========================================================================
    ###################
    def notify_user(self, target_user, command, data):
        ''' Send personal notification to target user '''
        query = pack_resp(command, resp_code=RESP.OK, data=data)

        # Put query into the queue to process locally
        # print "self.master.nickname", self.master.nickname
        # print "target_user", target_user
        if self.master.nickname == target_user:
            with self.lock:
                self.master.gui.tasks.put(query)
            return

        for session in self.sessions:
            if session.nickname == target_user:
                # If send was unsuccessful, close this socket
                if not tcp_send(session.client_sock, query):
                    # Close TCP Client socket before exit
                    close_socket(session.client_sock, "Close client socket(nickname: %s)." % session.nickname)
                    # del session
                break
        else:
            LOG.debug("User %s who should receive notification was not found" % target_user)

    def notify_other_users(self, command, data="", except_nickname=""):
        ''' Send notifications to all users except initiator '''
        query = pack_resp(command, resp_code=RESP.OK, data=data)

        # Put query into the queue to process locally
        print "self.master.nickname, except_nickname", self.master.nickname, except_nickname
        print "self.master.nickname", self.master.nickname
        if self.master.nickname != except_nickname and self.master.nickname is not None:
            with self.lock:
                self.master.gui.tasks.put(query)

        for session in self.sessions:
            if session.nickname != except_nickname and session.nickname is not None:
                # If send was unsuccessful, close this socket
                if not tcp_send(session.client_sock, query):
                    # Close TCP Client socket before exit
                    close_socket(session.client_sock, "Close client socket(nickname: %s)." % session.nickname)

    ###################
    # Main functions ===================================================================================
    ###################
    def reg_nickname(self, nickname):
        '''
        Register the username provided by user
        :param nickname: (str)
        '''
        resp_code, data, user_id = RESP.OK, "", None

        registered_names = [user_info["name"] for user_info in self.users.values()]

        # Check if the nickname already exists or not
        if nickname in registered_names:
            resp_code = RESP.NICKNAME_ALREADY_EXISTS
        else:
            with self.global_lock:
                self.users[self.last_user_id] = {
                    "name": nickname,
                    "status": ONLINE
                }
                user_id = self.last_user_id
                data = pack_data([user_id, nickname])

                self.last_user_id += 1  # for every new registration we should increment last_user_id

            # Notify other users about new registered user
            self.notify_other_users(
                command=COMMAND.NOTIFICATION.NEW_USER_REGISTERED,
                data=nickname,
                except_nickname=nickname
            )

        return resp_code, data, user_id

    def save_client_presence(self, user_id, nickname):
        with self.global_lock:
            self.user_id = int(user_id)
            self.nickname = nickname

            self.users[self.user_id] = {
                "name": nickname,
                "status": ONLINE
            }
            # Update counter for last registered user_id
            if self.user_id > self.last_user_id:
                self.last_user_id = self.user_id + 1
        # print "self.users after notif..", self.users

    def i_am_online(self, user_id, username):
        resp_code, data = RESP.OK, ""

        if user_id in self.users.keys():
            # Notify other users only if current user was offline
            if self.users[user_id]["status"] == OFFLINE:
                # Send notifications to other users that this user online
                self.notify_other_users(
                    command=COMMAND.NOTIFICATION.USER_ONLINE, data=username, except_nickname=username)

            # Mark user online
            self.users[user_id]["status"] = ONLINE

        return resp_code, data

    def i_am_offline(self, user_id, username):
        resp_code, data = RESP.OK, ""

        # Notify other users only if current user was offline
        if self.users[user_id]["status"] == ONLINE:
            # Send notifications to other users that this user offline
            self.notify_other_users(
                command=COMMAND.NOTIFICATION.USER_OFFLINE, data=username, except_nickname=username)

        # Mark user offline
        self.users[user_id]["status"] = OFFLINE

        return resp_code, data

    def send_msg(self, user_id, username, msg_time, chat_id, msg):
        ''' Here we save new msg from user '''
        resp_code, data = RESP.OK, ""
        chat_id = int(chat_id)

        if chat_id in self.chats.keys():
            msg_info = {
                "time_created": msg_time,
                "author_id": user_id,
                "msg": msg
            }

            # It's not the first msg
            if chat_id in self.msgs:
                self.msgs[chat_id].append(msg_info)
            # It's first message
            else:
                self.msgs[chat_id] = [msg_info]

            posted_msg = "(%s) %s: %s" % (msg_time, username, msg)
            data = pack_data([chat_id, posted_msg])

            # Notify other users in this chat (who are online)
            other_users = self.chats[chat_id]["participants_ids"]
            for participant_id in other_users:
                # All except current user who posted msg. Send it only who is online
                if participant_id != user_id and self.users[participant_id]["status"] == ONLINE:
                    target_user = self.users[participant_id]["name"]
                    self.notify_user(target_user, COMMAND.NOTIFICATION.NEW_MSG, data)

            # As a data we will return chat_id and msg
            posted_msg = "(%s) You: %s" % (msg_time, msg)
            data = pack_data([chat_id, posted_msg])
        else:
            resp_code = RESP.CHAT_DOES_NOT_EXIST
        return resp_code, data

    def all_msg(self, user_id, chat_id):
        ''' Here we fetch all msg in requested chat'''
        resp_code, data = RESP.OK, ""
        chat_id = int(chat_id)

        if chat_id in self.chats:
            msgs = [chat_id]

            # Fetch msgs (if they exist)
            if chat_id in self.msgs:
                chat_msgs = self.msgs[chat_id]

                for msg_info in chat_msgs:
                    who_posted = "You" if msg_info["author_id"] == user_id else self.users[msg_info["author_id"]]["name"]
                    posted_msg = "(%s) %s: %s" % (msg_info["time_created"], who_posted, msg_info["msg"])
                    msgs.append(posted_msg)
            # No msgs
            # else:
            #     pass

            data = pack_data(msgs)
        else:
            resp_code = RESP.CHAT_DOES_NOT_EXIST
        return resp_code, data

    def leave_chat(self, user_id, chat_id):
        resp_code, data = RESP.OK, ""
        chat_id = int(chat_id)

        if chat_id in self.chats:
            # Remove user from participants
            self.chats[chat_id]["participants_ids"].remove(user_id)

            username = self.users[user_id]["name"]  # user that left this chat
            data = pack_data([chat_id, username])

            for user_id in self.chats[chat_id]["participants_ids"]:
                target_user = self.users[user_id]["name"]
                self.notify_user(target_user, command=COMMAND.NOTIFICATION.USER_LEFT_CHAT, data=data)

                # Delete chat if it's empty
                # if len(chat_info["participants_ids"]) < 1:
                #     del self.chats[chat_id]
        else:
            resp_code = RESP.CHAT_DOES_NOT_EXIST
        return resp_code, data

    def create_chat(self, user_id, username, chat_name, chat_type, invited_users):
        resp_code, data = RESP.OK, ""

        registered_chats_names = [chat_info["name"] for chat_info in self.chats.values()]

        # Check if the nickname already exists or not
        if chat_name in registered_chats_names:
            resp_code = RESP.CHAT_NAME_ALREADY_EXISTS
        else:
            data = pack_data([self.last_chat_id, chat_name])

            if chat_type == PUBLIC:
                self.chats[self.last_chat_id] = {
                    "name": chat_name,
                    "type": chat_type,
                    "participants_ids": [user_id],
                    "owner_id": user_id
                }

                # Notify other users about new chat creation
                self.notify_other_users(
                    command=COMMAND.NOTIFICATION.NEW_CHAT_CREATED,
                    data=chat_name,
                    except_nickname=username
                )
            # Chat is private, then send invitations only for users who is invited
            else:
                invited_users_ids = [user_id]
                for invited_user in invited_users.split(","):
                    target_user_id = self.user_id_by_name(username=invited_user.strip())

                    # Check that given user_id is legal
                    if target_user_id is not None:
                        user_info = self.users[target_user_id]
                        invited_user = user_info["name"]

                        # Don't inform initiator, but only those who are online
                        if target_user_id != user_id and user_info["status"] == ONLINE:
                            invited_users_ids.append(target_user_id)
                            self.notify_user(
                                invited_user, command=COMMAND.NOTIFICATION.INVITED_TO_CHAT, data=chat_name
                            )

                self.chats[self.last_chat_id] = {
                    "name": chat_name,
                    "type": chat_type,
                    "participants_ids": invited_users_ids,
                    "owner_id": user_id
                }

            # for every new chat registration we should increment last_chat_id
            self.last_chat_id += 1

        return resp_code, data

    def join_chat(self, user_id, username, chat_name):
        resp_code, data = RESP.OK, ""
        chat_id = self.chat_id_by_name(chat_name)

        if chat_id in self.chats:
            # Add user to participants
            if user_id not in self.chats[chat_id]["participants_ids"]:
                self.chats[chat_id]["participants_ids"].append(user_id)

                # Notify other participants that this player join this chat
                for user_id in self.chats[chat_id]["participants_ids"]:
                    target_user = self.users[user_id]["name"]
                    data = pack_data([chat_id, username])

                    self.notify_user(target_user, COMMAND.NOTIFICATION.USER_JOINED_CHAT, data)

            # For response
            data = pack_data([chat_id, chat_name])
        else:
            resp_code = RESP.CHAT_DOES_NOT_EXIST

        return resp_code, data

    def chats_list(self, user_id):
        ''' Here we send only those chats which user can join (public/private) '''
        resp_code, data = RESP.OK, ""

        chats = []
        for chat_info in self.chats.values():
            chat_name = chat_info["name"]

            # Show only PUBLIC and PRIVATE chats if user is enrolled into them
            if chat_info["type"] == PUBLIC or user_id in chat_info["participants_ids"]:
                chats.append(chat_name)

        data = pack_data(chats)
        return resp_code, data

    def chat_participants(self, user_id, chat_id):
        '''
        Here we collect info about users in requested chat
        (but exclude current user_id)
        '''
        resp_code, data = RESP.OK, ""
        chat_id = int(chat_id)
        users_info = [chat_id]  # username, current_status

        if chat_id in self.chats:
            for participant_id in self.chats[chat_id]["participants_ids"]:
                if participant_id != user_id:
                    user = self.users[participant_id]

                    users_info.append(user["name"])
                    users_info.append(user["status"])

            data = pack_data(users_info)
        else:
            resp_code = RESP.CHAT_DOES_NOT_EXIST
        return resp_code, data

    def all_users(self, current_user_id):
        ''' Here we collect info about all users (except current user_id) '''
        resp_code, data = RESP.OK, ""
        users_info = []  # username, current_status

        print "self.users", self.users

        for user_id, user in self.users.items():
            if user_id != current_user_id:
                users_info.append(user["name"])
                users_info.append(user["status"])

        data = pack_data(users_info)

        return resp_code, data

    def user_id_by_name(self, username):
        ''' Find user id by username '''
        for user_id, user_info in self.users.items():
            if user_info["name"] == username:
                return user_id
        else:
            return None

    def chat_id_by_name(self, chat_name):
        ''' Find chat id by chat name '''
        for chat_id, chat_info in self.chats.items():
            if chat_info["name"] == chat_name:
                return chat_id
        else:
            return None


class Client(object):
    server_tcp_host, server_tcp_port = None, None
    sock = None  # TCP socket that is responsible for connection with server
    i_am_server = False   # if this peer has role a server then will be True

    def __init__(self):
        self.gui = None
        self.test = None  # Test regime
        self.lock = threading.Lock()  # to synchronize exit from "responses" and master threads
        self.stop_thread = False

        self.nickname = None

    ###################
    # Main functions to communicate with server via socket ==============================================
    ###################
    def discover_server(self, broadcast_port):
        ''' Do UDP broadcast to discover server '''

        def time_diff_in_secs(start_time):
            ''' Calculate time difference from start time to now '''
            curr_time = datetime.now()
            td_obj = curr_time - start_time  # timedelta object
            time_diff = td_obj.total_seconds()  # in seconds
            return time_diff

        tcp_host, tcp_port = None, None
        start_time = datetime.now()

        # Detect server to establish TCP connection
        udp_sock = socket(AF_INET, SOCK_DGRAM)
        udp_sock.bind(('', broadcast_port))

        select_timeout = 0.1

        # If we can't detect the server during 5 seconds, then return negative response
        while True:
            print "Try to find server online.."
            # Check if there is data available before call recv
            ready, _, _ = select.select([udp_sock], [], [], select_timeout)

            # If nothing is received yet, do the timeout with 0.1 secs
            if not ready:
                time.sleep(0.2)
            else:
                msg, (host, port) = udp_sock.recvfrom(BUFFER_SIZE)

                if "server_online" in msg:
                    LOG.info("Server is detected")
                    tcp_host, tcp_port = host, int(port)
                    break

            # If total time for searching for server is more than 2 seconds => exit and become a server
            if time_diff_in_secs(start_time) > 2:
                break

        # Make server host and port available inside Client object
        self.server_tcp_host, self.server_tcp_port = tcp_host, tcp_port

        # Close socket before exit
        if udp_sock:
            close_socket(udp_sock, "Close UDP socket on client.")

    def connect_to_server(self):
        ''' Connect to server through TCP connection '''
        # Try to connect until we exactly connect to the server (limit 5 tries)
        try_num, tries_number = 0, 5

        sock = socket(AF_INET, SOCK_STREAM)
        print 'TCP Socket created and started connecting..'

        while not self.sock and try_num != tries_number:
            try:
                sock.connect((self.server_tcp_host, self.server_tcp_port))
                self.sock = sock

                print 'TCP connection with server is established successfully'
            except socket_error as (code, msg):
                if code == 10061:
                    print 'Socket error occurred(tried connecting via TCP). Server does not respond.'
                else:
                    print 'Socket error occurred(tried connecting via TCP). Error code: %s, %s' % (code, msg)
                self.sock = None

            # Increment total number of tries
            try_num += 1
        return self.sock

    def request(self, command, data="", after_reconnect=False):
        '''
        This method sends requests to server over TCP connection
        :param data: (data)
        :param command: (enum) command
        :param after_reconnect: (bool) in case of after reconnecting
        '''
        data = str(data)
        print "<< Command(%s) + data(%s) sent to server" % (command_to_str(command), data[:10])

        query = pack_query(self.nickname, command, data)

        # If I'm currently a server-peer, process it now and put response into the queue
        if self.i_am_server:
            resp_msg = self.server.process_command(query)

            # Put resp_msg into the queue to process it locally
            with self.lock:
                self.gui.tasks.put(resp_msg)
            return

        try:
            self.sock.sendall(query)
        except:
            if not after_reconnect:
                print "TCP connection closed, but now try to reconnect to server.."

                self.connect_to_server()
                self.request(command, data, after_reconnect=True)

                # Restart notifications thread in infinite loop
                threading.Thread(name='NotificationsThread', target=self.notifications_loop).start()
            else:
                print "TCP couldn't send request even after reconnection.."

    ###################
    # Main functions(requests to server) ===============================================================
    ###################
    def check_nickname_existence(self):
        '''
        :return: (str) if nickname exists locally, return True. Otherwise False.
        '''

        # If the config exists, get the user_id from it
        if os.path.isfile(config_file) and not self.test:
            print "Nickname exists locally"

            conf = CP.ConfigParser()
            conf.read(config_file)

            self.nickname = conf.get('USER_INFO', 'nickname')
            self.user_id = int(conf.get('USER_INFO', 'user_id'))

            # Notify server about existence of nickname and user_id
            data = pack_data([self.user_id, self.nickname])
            print "data", data, [self.user_id, self.nickname]
            self.request(COMMAND.NOTIFY_ABOUT_USER_ID, data)

            return True

        # Nickname wasn't found in local config
        else:
            return False

    def save_nickname_locally(self, nickname, user_id):
        ''' Save nickname in local config file '''
        self.nickname = nickname
        self.user_id = int(user_id)

        conf = CP.RawConfigParser()
        conf.add_section("USER_INFO")
        conf.set('USER_INFO', 'nickname', self.nickname)
        conf.set('USER_INFO', 'user_id', self.user_id)

        # If it's not test running script, then save nickname locally
        if not self.test:
            with open(config_file, 'w') as cf:
                conf.write(cf)
        # else:
            # make timeout 0.5 sec, that slave thread could assign self.chat_id
            # time.sleep(0.5)

    def reg_nickname(self, nickname):
        '''
        Register the nickname provided by user
        :param nickname: (str)
        '''
        self.request(COMMAND.REG_NICKNAME, data=nickname)

    def i_am_online(self):
        self.request(COMMAND.I_AM_ONLINE)

    def i_am_offline(self):
        self.request(COMMAND.I_AM_OFFLINE)

    def send_msg(self, msg):
        ''' Send current time and user's msg to server '''
        chat_id = self.gui.chat_id
        curr_time = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        data = pack_data([curr_time, chat_id, msg])

        self.request(COMMAND.SEND_MSG, data)

    def all_msgs(self):
        ''' Get all msgs from the server '''
        self.request(COMMAND.ALL_MSGS, data=self.gui.chat_id)

    def leave_chat(self):
        chat_id = self.gui.chat_id
        self.request(COMMAND.LEAVE_CHAT, data=chat_id)

    def create_chat(self, chat_name, chat_type, invited_users):
        data = pack_data([chat_name, chat_type, invited_users])

        self.request(COMMAND.CREATE_CHAT, data)

    def join_chat(self, chat_name):
        self.request(COMMAND.JOIN_CHAT, data=chat_name)

    def chats_list(self):
        self.request(COMMAND.CHATS_LIST)

    def chat_participants(self):
        self.request(COMMAND.CHAT_PARTICIPANTS, data=self.gui.chat_id)

    def all_users(self):
        self.request(COMMAND.ALL_USERS)

    #############
    # Main loop for receiving responses/notifications ==================================================
    #############
    def notifications_loop(self):
        ''' Main Receiver of responses/notifications from the server (over TCP connection) '''
        LOG.info('Notif. thread is running and started to listen...')

        while not self.stop_thread:
            msg = tcp_receive(self.sock)

            if msg:
                # Put task into the queue that another thread could process it
                with self.lock:
                    self.gui.tasks.put(msg)
            else:
                break

        # Close socket before exit
        with self.lock:
            if self.sock:
                close_socket(self.sock, "Close client socket (in notif. thread).")


def main():
    # Parsing arguments
    parser = ArgumentParser()
    parser.add_argument('-udp_p', '--udp_broadcast_port', default=DEFAULT_BROADCAST_PORT,
                        help='To discover server on specified port through broadcasting,'
                             'default is %s' % DEFAULT_BROADCAST_PORT)
    # This argument is to run several clients just for test
    parser.add_argument('-t', '--test', action='store_true',
                        help='For testing client side on several clients'
                             '(without argument and it doesn\'t save nickname locally.)')
    parser.print_help()
    args = parser.parse_args()

    # Before Client starts working, we need to check connections to RabbitMQ and Redis
    client = Client()
    gui = GUI()

    # Client can trigger GUI and vice-versa (at anytime)
    client.gui = gui
    gui.client = client

    client.test = args.test

    # Discover server
    client.discover_server(broadcast_port=args.udp_broadcast_port)

    # If server has not been found, exit
    if client.server_tcp_host is None:
        client.i_am_server = True
        # Run server
        server = Main_Server(master=client)

        # Run broadcasting through UDP connection
        threading.Thread(target=server.main_loop, args=(args.udp_broadcast_port, global_lock, )).start()
        print "Now it is a PEER-SERVER"

        # Simulate client session for PEER-SERVER
        client.server = ClientSession(client_sock=None, server=server, i_am_server=True)
    else:
        # If we couldn't connect to server via TCP, server doesn't respond
        if client.connect_to_server() is None:
            return

        # Start notifications thread in infinite loop
        threading.Thread(name='NotificationsThread', target=client.notifications_loop).start()

    # Now we can run Peer
    print "####################"
    print "Peer is running"

    # if nickname already exists, then run main menus
    if client.check_nickname_existence():
        # Run main menu window
        gui.main_menu_window()

    else:
        # Launch GUI window to ask the user to provide his/her enter nickname
        gui.nickname_window()

    with client.lock:
        client.stop_thread = True

    # Close socket
    if client.sock:
        close_socket(client.sock, "Close client socket.")

    print 'Terminating ...'


if __name__ == "__main__":
    main()
