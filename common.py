from socket import error as socket_error
from sys import path, argv
import logging
import os
import select
import time


# Extend PYTHONPATH for working directory----------------------------------
a_path = os.path.sep.join(os.path.abspath(argv[0]).split(os.path.sep)[:-1])
path.append(a_path)


# Setup Python logging --------------------------------------------------------
FORMAT = '%(asctime)-15s %(levelname)s %(message)s'
logging.basicConfig(level=logging.DEBUG, format=FORMAT)
LOG = logging.getLogger()


# Info--------------------------------------------------------------------------
___NAME = "P2P Chat (Discover server through receiving broadcast from server)"
___VER = "0.0.1"


def __info():
    return '%s version %s' % (___NAME, ___VER)

# Constants -------------------------------------------------------------------
DEFAULT_BROADCAST_PORT = 50000
BUFFER_SIZE = 1024  # Receive not more than 1024 bytes per 1 msg

ONLINE, OFFLINE = '1', '0'
PUBLIC, PRIVATE = '0', '1'

SEP = "_-_"  # separate command and data in request
SEP_DATA = "_+--+_"
TERM_CHAR = "|.|"  # terminator characters (means end of the msg)
# TIMEOUT = 5  # in seconds


# "Enum" for commands
def enum(**vals):
    return type('Enum', (), vals)


COMMAND = enum(
    REG_NICKNAME='1',  # register nickname
    I_AM_ONLINE='2',  # user become online
    I_AM_OFFLINE='3',  # user become offline
    SEND_MSG='4',
    ALL_MSGS='5',  # all msgs in particular chat
    LEAVE_CHAT='6',
    CREATE_CHAT='7',
    JOIN_CHAT='8',

    CHATS_LIST='9',
    CHAT_PARTICIPANTS='10',
    ALL_USERS='11',
    NOTIFY_ABOUT_USER_ID='12',

    # Notifications from the server
    NOTIFICATION=enum(
        USER_OFFLINE='21',
        USER_ONLINE='22',
        NEW_MSG='23',
        INVITED_TO_CHAT='24',
        NEW_CHAT_CREATED='25',

        NEW_USER_REGISTERED='26',
        USER_LEFT_CHAT='27',
        USER_JOINED_CHAT='28'
    )
)


# Responses
RESP = enum(
    OK='0',
    FAIL='1',
    NICKNAME_ALREADY_EXISTS='2',
    NO_USERS_FOUND='3',  # in case of inviting to chat
    CHAT_NAME_ALREADY_EXISTS='4',
    CHAT_DOES_NOT_EXIST='5',
)


# Main functions ---------------------------------------------------------------
def resp_code_to_str(resp_code):
    '''
    :param err_code: code of the error
    :return: (string) definition of the error
    '''
    global RESP
    err_text = ""

    if resp_code == RESP.OK:
        err_text = "No errors"
    elif resp_code == RESP.FAIL:
        err_text = "Bad result"
    elif resp_code == RESP.NICKNAME_ALREADY_EXISTS:
        err_text = "Requested nickname already exists"
    elif resp_code == RESP.NO_USERS_FOUND:
        err_text = "NO_USERS_FOUND"
    elif resp_code == RESP.CHAT_NAME_ALREADY_EXISTS:
        err_text = "CHAT_NAME_ALREADY_EXISTS"
    elif resp_code == RESP.CHAT_DOES_NOT_EXIST:
        err_text = "CHAT_DOES_NOT_EXIST"
    return err_text


def command_to_str(command):
    '''
    Represent command meaning as string
    :param command: (str) - command code from enum COMMAND
    :return text: (str) - explanation of the command
    '''
    global COMMAND
    text = ""

    if command == COMMAND.REG_NICKNAME:
        text = "Register nickname"
    elif command == COMMAND.I_AM_ONLINE:
        text = "I_AM_ONLINE"
    elif command == COMMAND.I_AM_OFFLINE:
        text = "I_AM_OFFLINE"
    elif command == COMMAND.SEND_MSG:
        text = "SEND_MSG"
    elif command == COMMAND.ALL_MSGS:
        text = "ALL_MSGS"
    elif command == COMMAND.LEAVE_CHAT:
        text = "LEAVE_CHAT"
    elif command == COMMAND.CREATE_CHAT:
        text = "CREATE_CHAT"
    elif command == COMMAND.JOIN_CHAT:
        text = "JOIN_CHAT"
    elif command == COMMAND.CHATS_LIST:
        text = "CHATS_LIST"
    elif command == COMMAND.CHAT_PARTICIPANTS:
        text = "CHAT_PARTICIPANTS"
    elif command == COMMAND.ALL_USERS:
        text = "ALL_USERS"
    elif command == COMMAND.NOTIFY_ABOUT_USER_ID:
        text = "NOTIFY_ABOUT_USER_ID"

    # Notifications
    elif command == COMMAND.NOTIFICATION.USER_OFFLINE:
        text = "Notif. USER_OFFLINE"
    elif command == COMMAND.NOTIFICATION.USER_ONLINE:
        text = "Notif. USER_ONLINE"
    elif command == COMMAND.NOTIFICATION.NEW_MSG:
        text = "Notif. NEW_MSG"
    elif command == COMMAND.NOTIFICATION.INVITED_TO_CHAT:
        text = "Notif. INVITED_TO_CHAT"
    elif command == COMMAND.NOTIFICATION.NEW_CHAT_CREATED:
        text = "Notif. NEW_CHAT_CREATED"
    elif command == COMMAND.NOTIFICATION.NEW_USER_REGISTERED:
        text = "Notif. NEW_USER_REGISTERED"
    elif command == COMMAND.NOTIFICATION.USER_LEFT_CHAT:
        text = "Notif. USER_LEFT_CHAT"
    elif command == COMMAND.NOTIFICATION.USER_JOINED_CHAT:
        text = "Notif. USER_JOINED_CHAT"
    return text


def pack_query(username, command, data=""):
    '''
    :param username : (str) user nickname
    :param command: (enum)
    :param data: (str) packed data
    :return: packed elements from the list separated by separator
    '''
    username = username if username else ""
    return SEP.join([username, command, str(data)]) + TERM_CHAR


def pack_resp(command, resp_code, data=""):
    '''
    :param command: (enum)
    :param data: (str) packed data
    :return: splitted elements by separator
    '''
    return SEP.join([str(command), str(resp_code), str(data)]) + TERM_CHAR


def pack_data(data):
    '''
    :param data: (list) of values to pack
    :return: (str) - packed data joined by SEP_DATA separator
    '''
    data = [str(el) for el in data]
    return SEP_DATA.join(data)


def parse_query(raw_data):
    '''
    :param raw_data: string that may contain command and data
    :return: (command, data)
    '''
    # Split the string by separator to get the command and data
    raw_data = raw_data[:-len(TERM_CHAR)]
    nickname, command, data = raw_data.split(SEP)
    return nickname, command, data


def parse_response(raw_response):
    '''
    :param raw_response: string that may contain command, resp_code, data
    :return: (command, data)
    '''
    # Split string by separator to get the command and data
    raw_response = raw_response[:-len(TERM_CHAR)]
    command, resp_code, data = raw_response.split(SEP)
    return command, resp_code, data


def parse_data(raw_data):
    '''
    :param raw_data: (str)
    :return: (list)
    '''
    # Split string by SEP_DATA separator to get data list from raw_data
    return raw_data.split(SEP_DATA)


def tcp_send(sock, query):
    '''  TCP send request
    @param sock: TCP socket
    @param query: packed data (command, data)
    '''
    # print "data to send: %s, len: %s" % (data, len(data))
    print "<< Query \"%s\" sent" % query
    try:
        sock.sendall(query)
        return True
    except:
        return False


def tcp_receive(sock, buffer_size=BUFFER_SIZE):
    '''
    :param sock: TCP socket
    :param buffer_size: max possible size of message per one receive call
    :return: message without terminate characters
    '''
    m = ''
    while True:
        try:
            # Receive one block of data according to receive buffer size
            block = sock.recv(buffer_size)
            m += block
        except socket_error as (code, msg):
            if code == 10054:
                LOG.error('Server is not available.')
            else:
                LOG.error('Socket error occurred. Error code: %s, %s' % (code, msg))
            return None

        if m.endswith(TERM_CHAR):
            break
    return m


def close_socket(sock, log_msg=""):
    # Check if the socket is closed already
    # in this case there can be no I/O descriptor
    try:
        sock.fileno()
    except socket_error:
        LOG.debug('Socket already closed...')
        return

    # Close socket, remove I/O descriptor
    sock.close()

    if len(log_msg) > 0:
        LOG.debug(log_msg)
