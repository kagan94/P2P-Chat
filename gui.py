import time
import tkMessageBox
import Queue
from Tkinter import *
from ScrolledText import *

# Local import
from common import *


class GUI:
    def __init__(self):
        # Queue to collect and process the responses/notifications from server
        self.tasks = Queue.Queue()

        self.client = None
        self.root = None
        self.new_chat_root = None
        self.root_name = None

        self.chat_id = None  # current chat_id where the user sits

    def run_root(self, root):
        '''
        Run given tkinter window (root).
        Allow to do some other actions when the window is show
        which root.mainloop() doesn't allow to do
        '''
        while True:
            # Put received task into the queue to process it
            try:
                task = self.tasks.get(False)
            # Handle empty queue here
            except Queue.Empty:
                pass
            else:
                # Trigger another method that will do some actions depending on msg content
                self.process_task(task)
                self.tasks.task_done()

            # Equivalent to self.mainloop() but with timeout.
            # Because we need to check our queue with tasks, we used this construction
            try:
                root.update_idletasks()
                root.update()
                time.sleep(0.1)

            # Catch error "can't invoke "update" command: application has been destroyed
            except(TclError, KeyboardInterrupt):
                # Trigger methods "on_exit" when the loop breaks
                self.on_exit()
                return

            except AttributeError:
                print "Error: root can't be NoneType"
                break

    def nickname_window(self):
        self.root = Tk()
        self.root.title("Enter a nickname")
        self.root_name = "reg_nickname"
        self.root.geometry("300x130")

        self.nickname_var = StringVar()

        Label(self.root, text="You don't have nickname.").pack(pady=5)
        Label(self.root, text="Enter your nickname").pack(pady=3)
        Entry(self.root, textvariable=self.nickname_var).pack()

        self.reg_nickname_b = Button(self.root, text="Register nickname", command=self.on_reg_nickname_submit)
        self.reg_nickname_b.pack(pady=5)

        self.run_root(self.root)

    def main_menu_window(self):
        # Destroy previous window
        self.destroy_previous_root()

        # Trigger server to mark me as online
        self.client.i_am_online()

        self.root = Tk()
        self.root.title('Main menu')
        self.root_name = "main_menu"
        self.chat_id = None

        # Header
        Label(self.root, text="All users").grid(row=0, column=0)
        Label(self.root, text="All chats").grid(row=0, column=1)

        # Middle part
        self.users_l = Listbox(self.root, width=20, height=18)
        self.chats_l = Listbox(self.root, width=20, height=18)

        self.users_l.grid(row=1, column=0)
        self.chats_l.grid(row=1, column=1)

        # Footer part (go_to_create_chat + join_chat buttons)
        Button(self.root, text="Create chat", command=self.on_go_to_create_chat_window).grid(row=2, column=1)
        self.join_chat_b = Button(self.root, text="Join to a chat", command=self.on_join_chat).grid(row=3, column=1)

        # Request to get "all_users" and "all_chats" lists
        self.client.all_users()
        self.client.chats_list()

        self.root.protocol('WM_DELETE_WINDOW', self.on_exit)
        self.run_root(self.root)

    def create_chat_window(self):
        self.new_chat_root = Tk()
        self.new_chat_root.title("Create new chat")

        self.chat_name_var = StringVar(self.new_chat_root)
        self.invited_users_var = StringVar(self.new_chat_root)
        self.chat_type_var = StringVar(self.new_chat_root)

        Label(self.new_chat_root, text="Chat name").pack()
        Entry(self.new_chat_root, textvariable=self.chat_name_var, width=40).pack()

        chatTypeFrame = Frame(self.new_chat_root)
        Label(self.new_chat_root, text="Chat type").pack(pady=(10, 0))

        public = Radiobutton(chatTypeFrame, text="Public", variable=self.chat_type_var, value=PUBLIC)
        private = Radiobutton(chatTypeFrame, text="Private", variable=self.chat_type_var, value=PRIVATE)
        public.select()  # By default the "public" is selected

        public.grid(row=0, column=0)
        private.grid(row=0, column=1)
        chatTypeFrame.pack()

        Label(self.new_chat_root, text="Usernames which should be invited \n(separated by comma ',')").pack(pady=(10, 0))
        Entry(self.new_chat_root, textvariable=self.invited_users_var, width=40).pack(padx=10)

        self.create_chat_b = Button(self.new_chat_root, text="Create chat", command=self.on_create_chat_submit)
        self.create_chat_b.pack(pady=10)

    def chat_window(self, chat_name):
        # Destroy previous window
        self.destroy_previous_root()

        self.root = Tk()
        self.root.title('Chat - %s' % chat_name)
        self.root_name = "chat"

        self.msg_var = StringVar(self.root)

        Label(self.root, text="Chat name: %s" % chat_name).grid(row=0, column=0, columnspan=2)

        # Middle Right Frame
        mrFrame = Frame(self.root)
        mrFrame.grid(row=1, column=1)

        self.chat_msgs = ScrolledText(mrFrame, width=40, height=20)
        self.chat_msgs.grid(row=0, column=0)

        # Middle Left Frame
        mlFrame = Frame(self.root)
        mlFrame.grid(row=1, column=0)

        Label(mlFrame, text="Users").grid(row=0, column=0)
        self.users_l = Listbox(mlFrame, width=20, height=18)
        self.users_l.grid(row=1, column=0)

        # Bottom part (msg_field + "send" button)
        bFrame = Frame(self.root)
        bFrame.grid(row=2, column=1)

        msg_field = Entry(bFrame, width=30, textvariable=self.msg_var)
        self.leave_chat_b = Button(bFrame, text="Leave this chat", command=self.on_leave_chat)
        self.leave_chat_b.grid(row=0, column=1, sticky=W + E)
        Button(bFrame, text="Send msg", command=self.on_send_msg).grid(row=1, column=0, sticky=W + E + N + S)
        Button(bFrame, text="Go to main menu", command=self.main_menu_window).grid(row=0, column=3)

        msg_field.grid(row=0, column=0)
        msg_field.bind('<Return>', self.on_send_msg)

        # Init requests to load chat participants and posted msgs
        self.client.chat_participants()
        self.client.all_msgs()

        self.root.protocol('WM_DELETE_WINDOW', self.on_exit)
        self.run_root(self.root)

    #################
    # Additional methods
    def clean_users_list(self):
        ''' Just clean all users in users list '''
        self.users_l.delete(0, END)

    def user_pos_in_list(self, username):
        ''' Find user position in list by his/her username'''
        try:
            users = self.users_l.get(0, END)
        except TclError:
            return

        # Find user in list by his username
        for pos, el in enumerate(users):
            if el.strip() == username:
                return pos
        else:
            return None

    def add_user_to_list(self, username):
        self.users_l.insert(END, username)

    def remove_user_from_list(self, username):
        user_pos_in_list = self.user_pos_in_list(username=username)

        if user_pos_in_list is not None:
            self.users_l.delete(user_pos_in_list)

    def mark_user_in_list(self, username, status):
        '''
        Mark user in the users list depending on his/her status
        :param username: (str)
        :param status: (str) can be ONLINE/OFFLINE
        '''
        pos_in_list = self.user_pos_in_list(username=username)

        # If user was found, then mark him
        if pos_in_list is not None:
            if status == ONLINE:
                print "player %s marked as online" % username
                self.users_l.itemconfig(pos_in_list, bg='green')

            elif status == OFFLINE:
                self.users_l.itemconfig(pos_in_list, bg='white')

    def clean_chats_list(self):
        ''' Just clean all chats in chats list '''
        self.chats_l.delete(0, END)

    def add_chat_to_list(self, chat_name):
        if self.chats_l.size() == 0:
            self.clean_chats_list()
            self.chats_l.insert(0, chat_name)
        else:
            self.chats_l.insert(END, chat_name)

    ####################################
    # HANDLERS
    def on_reg_nickname_submit(self):
        print "on_reg_nickname_submit"
        nickname = self.nickname_var.get()

        if nickname == "":
            self.show_error("Please enter valid nickname")
        else:
            self.reg_nickname_b.config(state=DISABLED)
            self.client.reg_nickname(nickname)

    def on_create_chat_submit(self):
        print "on_create_chat_submit"

        chat_name = self.chat_name_var.get()
        chat_type = self.chat_type_var.get()
        invited_users = self.invited_users_var.get()

        if chat_name == "":
            self.show_error("Chat name can't be empty")
        elif chat_type == PRIVATE and invited_users == "":
            self.show_error("Enter at least 1 username that should be invited")
        else:
            # Block the button until we'll receive the answer from server
            self.create_chat_b.config(state=DISABLED)

            # Init request to create chat
            self.client.create_chat(chat_name, chat_type, invited_users)

    def on_send_msg(self, event=None):
        msg = self.msg_var.get()

        # Put it's into msg processing
        if msg != "":
            self.client.send_msg(msg)
            print "msg %s sent" % msg

            # Reset msg field
            self.msg_var.set("")

    def on_go_to_create_chat_window(self):
        print "Run create chat window.."
        self.create_chat_window()

    def on_join_chat(self):
        # Get selected chat name
        widget = self.chats_l
        try:
            index = int(widget.curselection()[0])
            selected_chat = widget.get(index).strip()
        except:
            selected_chat = None

        print "on_join_chat"

        if selected_chat:
            # Put request to the server
            self.client.join_chat(selected_chat)

    def on_leave_chat(self):
        self.leave_chat_b.config(state=DISABLED)
        self.client.leave_chat()

    def on_exit(self):
        ''' On exit (while user press cross) '''
        # mark user as offline and destroy all windows
        self.client.i_am_offline()
        self.destroy_previous_root()

    ######################
    # OTHER METHODS
    def destroy_previous_root(self):
        ''' Destroy previous window '''

        # Destroy window "enter nickname" / chat / main_menu
        if self.root:
            try:
                self.root.destroy()
            except TclError:
                # App already destroyed
                pass
            self.root = None

        # Destroy "create new chat room" window
        if self.new_chat_root:
            try:
                self.new_chat_root.destroy()
            except TclError:
                pass
            self.new_chat_root = None

    def add_new_msg(self, msg):
        ''' Append new msg to the end of text field '''
        self.chat_msgs.insert(END, msg + "\n")

    def show_error(self, msg):
        tkMessageBox.showerror("Error", msg)

    def show_msg(self, msg):
        tkMessageBox.showinfo("Info", msg)

    ####################
    # Important function to process responses from servers
    ####################
    def process_task(self, msg):
        ''' Main handler for processing responses and notifications '''
        # Parse the response/notification
        # print "msg", msg.split(SEP)
        command, resp_code, data = parse_response(msg)

        print ">> Received resp(%s) on command: %s" % (resp_code_to_str(resp_code), command_to_str(command))

        # And process it depending on the command
        if command == COMMAND.REG_NICKNAME:
            # self.client.resp_reg_nick = True

            if resp_code == RESP.OK:
                user_id, nickname = parse_data(data)
                print "COMMAND.REG_NICKNAME", parse_data(data)

                self.client.save_nickname_locally(nickname, user_id)
                self.main_menu_window()
            else:
                error = resp_code_to_str(resp_code)
                self.show_error(error)
                self.reg_nickname_b.config(state=NORMAL)

        elif command == COMMAND.I_AM_ONLINE:
            pass

        elif command == COMMAND.I_AM_OFFLINE:
            pass

        elif command == COMMAND.SEND_MSG:
            if resp_code == RESP.OK:
                chat_id, msg = parse_data(data)

                # if the window chat is launched and current chat corresponds to a given chat_id
                if self.root_name == "chat" and self.chat_id == int(chat_id):
                    self.add_new_msg(msg)
            else:
                error = resp_code_to_str(resp_code)
                self.show_error(error)

        elif command == COMMAND.ALL_MSGS:
            if resp_code == RESP.OK:
                msgs_info = parse_data(data)
                chat_id = msgs_info.pop(0)

                print "chat_id", chat_id

                # If user is in chat window and chat_id is the same with chat_id from response
                # Then upload all msgs in the msgs area
                if self.root_name == "chat" and self.chat_id == int(chat_id):
                    for msg in msgs_info:
                        self.add_new_msg(msg)
            else:
                error = resp_code_to_str(resp_code)
                self.show_error(error)

        elif command == COMMAND.LEAVE_CHAT:
            if resp_code == RESP.OK:
                self.chat_id = None
                self.main_menu_window()
            else:
                # Unblock "leave_chat" button and show error
                self.leave_chat_b.config(state=NORMAL)

                error = resp_code_to_str(resp_code)
                self.show_error(error)

        elif command == COMMAND.CREATE_CHAT:
            if resp_code == RESP.OK:
                chat_id, chat_name = parse_data(data)

                self.add_chat_to_list(chat_name)
                self.show_msg("Chat \"%s\" has been created" % chat_name)

                # # Run window with this chat
                if self.root_name == "main_menu":
                    self.chat_id = int(chat_id)
                    self.chat_window(chat_name)
            else:
                # Unblock button "create_chat" and show error
                self.create_chat_b.config(state=NORMAL)

                error = resp_code_to_str(resp_code)
                self.show_error(error)

        elif command == COMMAND.JOIN_CHAT:
            if resp_code == RESP.OK:
                chat_id, chat_name = parse_data(data)
                self.chat_id = int(chat_id)

                # Run window with this chat
                self.chat_window(chat_name)
            else:
                # Unblock button "create_chat" and show error
                self.join_chat_b.config(state=NORMAL)

                error = resp_code_to_str(resp_code)
                self.show_error(error)

        elif command == COMMAND.CHATS_LIST:
            chat_info = parse_data(data)

            self.clean_chats_list()

            for chat_name in chat_info:
                self.add_chat_to_list(chat_name)

        elif command == COMMAND.CHAT_PARTICIPANTS:
            if resp_code == RESP.OK:
                users_info = parse_data(data)
                chat_id = int(users_info.pop(0))

                # If user is in the same chat room that is from response
                # then update chat participants
                if self.root_name == "chat" and chat_id == self.chat_id:
                    self.clean_users_list()

                    for i in range(0, len(users_info), 2):
                        username = users_info[i]
                        status = users_info[i + 1]

                        print status

                        self.add_user_to_list(username)
                        self.mark_user_in_list(username, status)
            else:
                error = resp_code_to_str(resp_code)
                self.show_error(error)

        elif command == COMMAND.ALL_USERS:
            if self.root_name == "main_menu":
                users_info = parse_data(data)

                self.clean_users_list()

                # Check that user info is not empty
                if users_info[0] != "":
                    for i in range(0, len(users_info), 2):
                        username = users_info[i]
                        status = users_info[i + 1]

                        self.add_user_to_list(username)
                        self.mark_user_in_list(username, status)

        # elif command == COMMAND.NOTIFY_ABOUT_USER_ID:
        #     pass

        # Notifications
        elif command == COMMAND.NOTIFICATION.USER_OFFLINE:
            self.mark_user_in_list(username=data, status=OFFLINE)

        elif command == COMMAND.NOTIFICATION.USER_ONLINE:
            self.mark_user_in_list(username=data, status=ONLINE)

        elif command == COMMAND.NOTIFICATION.NEW_MSG:
            chat_id, msg = parse_data(data)

            # if the window chat is launched and current chat corresponds to a given chat_id
            if self.root_name == "chat" and self.chat_id == int(chat_id):
                self.add_new_msg(msg)

        elif command == COMMAND.NOTIFICATION.INVITED_TO_CHAT:
            chat_name = data

            # If user is in the main menu, update chats list
            if self.root_name == "main_menu":
                self.add_chat_to_list(chat_name)

            # Otherwise raise notification for him/her
            else:
                self.show_msg("New chat created and you have been invited to the chat \"%s\"" % chat_name)

        elif command == COMMAND.NOTIFICATION.NEW_CHAT_CREATED:
            chat_name = data

            # If user is in the main menu, update chats list
            if self.root_name == "main_menu":
                self.add_chat_to_list(chat_name)

            # Otherwise raise notification for him/her
            else:
                self.show_msg("New chat \"%s\" created" % chat_name)

        elif command == COMMAND.NOTIFICATION.NEW_USER_REGISTERED:
            if self.root_name == "main_menu":
                self.add_user_to_list(username=data)
                self.mark_user_in_list(username=data, status=ONLINE)

        elif command == COMMAND.NOTIFICATION.USER_LEFT_CHAT:
            chat_id, username = parse_data(data)

            if self.root_name == "chat" and self.chat_id == int(chat_id):
                self.remove_user_from_list(username=username)
                print "user %s was removed from users list" % username

        elif command == COMMAND.NOTIFICATION.USER_JOINED_CHAT:
            chat_id, username = parse_data(data)

            if self.root_name == "chat" and self.chat_id == int(chat_id):
                self.add_user_to_list(username=username)
                self.mark_user_in_list(username=username, status=ONLINE)
