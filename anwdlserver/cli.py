"""
    Copyright 2023 The Anweddol project
    See the LICENSE file for licensing informations
    ---

    CLI : Main anwdlserver CLI process

"""
from datetime import datetime
import daemon.pidfile
import argparse
import hashlib
import daemon
import signal
import time
import json
import pwd
import sys
import os

# Intern importation
from .core.crypto import RSAWrapper, DEFAULT_RSA_KEY_SIZE
from .core.utilities import isPortBindable
from .tools.access_token import AccessTokenManager

from .utilities import createFileRecursively, checkServerEnvironment, Colors
from .config import loadConfigurationFileContent
from .process import launchServerProcess
from .__init__ import __version__

# Constants definition
CONFIG_FILE_PATH = (
    "C:\\Windows\\Anweddol\\config.yaml"
    if os.name == "nt"
    else "/etc/anweddol/config.yaml"
)

LOG_JSON_STATUS_SUCCESS = "OK"
LOG_JSON_STATUS_ERROR = "ERROR"


class MainAnweddolServerCLI:
    def __init__(self):
        self.json = False

        parser = argparse.ArgumentParser(
            formatter_class=argparse.RawDescriptionHelpFormatter,
            usage=f"""{sys.argv[0]} <command> [OPT]

\033[1mThe Anweddol server CLI implementation.\033[0m
Provide clients with containers and manage them.

Version {__version__}

server lifecycle commands:
  start       start the server
  stop        stop the server
  restart     restart the server

server management commands:
  access-tk   manage access tokens
  regen-rsa   regenerate RSA keys""",
            epilog="""---
If you encounter any problems while using this tool,
please report it by opening an issue on the repository : 
 -> https://github.com/the-anweddol-project/Anweddol-server/issues""",
        )
        parser.add_argument("command", help="command to execute (see above)")
        args = parser.parse_args(sys.argv[1:2])

        if not hasattr(self, args.command.replace("-", "_")):
            parser.print_help()
            exit(-1)

        try:
            if not os.path.exists(CONFIG_FILE_PATH):
                raise FileNotFoundError(f"{CONFIG_FILE_PATH} was not found on system")

            self.config_content = loadConfigurationFileContent(CONFIG_FILE_PATH)

            if not self.config_content[0]:
                raise ValueError(
                    f"Configuration file is invalid -> \n{json.dumps(self.config_content[1], indent=4)}"
                )
                exit(-1)

            self.config_content = self.config_content[1]

            exit(getattr(self, args.command.replace("-", "_"))())

        except Exception as E:
            if type(E) is KeyboardInterrupt:
                self.__log_stdout("")
                exit(0)

            if self.json:
                self.__log_json(
                    LOG_JSON_STATUS_ERROR, "An error occured", data={"error": str(E)}
                )

            else:
                self.__log_stdout("An error occured : ", color=Colors.RED, end="")
                self.__log_stdout(f"{E}\n")

            exit(-1)

    def __log_stdout(self, message, bypass=False, color=None, end="\n"):
        if not bypass:
            print(f"{color}{message}\033[0;0m" if color else message, end=end)

    def __log_json(self, status, message, data={}):
        print(json.dumps({"status": status, "message": message, "data": data}))

    def start(self):
        parser = argparse.ArgumentParser(
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description="\033[1m-> Start the server\033[0m",
            usage=f"{sys.argv[0]} start [OPT]",
        )
        parser.add_argument(
            "-c",
            help="check environment validity",
            action="store_true",
        )
        parser.add_argument(
            "-d",
            help="execute the server in direct mode (parent terminal). Server will run as the actual effective user",
            action="store_true",
        )
        parser.add_argument(
            "-y", "--assume-yes", help="answer 'y' to any prompts", action="store_true"
        )
        parser.add_argument(
            "-n", "--assume-no", help="answer 'n' to any prompts", action="store_true"
        )
        parser.add_argument(
            "--enable-stdout-log",
            help="display logs in stdout or not",
            action="store_true",
        )
        parser.add_argument(
            "--enable-traceback-log",
            help="enable tracebacks in logs or not",
            action="store_true",
        )
        parser.add_argument(
            "--skip-check", help="skip environment validity check", action="store_true"
        )
        parser.add_argument(
            "--json", help="print output in JSON format", action="store_true"
        )
        args = parser.parse_args(sys.argv[2:])

        self.json = args.json

        if not args.skip_check:
            check_result_list = checkServerEnvironment(self.config_content)

            if args.c:
                if args.json:
                    self.__log_json(
                        LOG_JSON_STATUS_SUCCESS,
                        "Check done",
                        data={
                            "errors_recorded": len(check_result_list),
                            "errors_list": check_result_list,
                        },
                    )

                else:
                    self.__log_stdout("Check done, ", end="")
                    self.__log_stdout(
                        f"{len(check_result_list)} errors recorded :",
                        color=Colors.RED if len(check_result_list) else Colors.GREEN,
                    )

                    for error in check_result_list:
                        self.__log_stdout(f"- {error}")

                    self.__log_stdout("")

                return 0

            if len(check_result_list) != 0:
                if args.json:
                    self.__log_json(
                        LOG_JSON_STATUS_ERROR,
                        "Errors detected on server environment",
                        data={
                            "errors_recorded": len(check_result_list),
                            "errors_list": check_result_list,
                        },
                    )

                    return -1

                else:
                    self.__log_stdout(
                        "Server environment is invalid : ", color=Colors.RED
                    )

                    for error in check_result_list:
                        self.__log_stdout(f"- {error}")

                    self.__log_stdout("")

                    raise EnvironmentError(
                        f"{len(check_result_list)} error(s) detected on server environment"
                    )

        pid_file_path = self.config_content["server"].get("pid_file_path")

        if os.path.exists(pid_file_path):
            self.__log_stdout(
                f"A PID file already exists on {pid_file_path}",
                bypass=args.json,
                color=Colors.ORANGE,
            )
            choice = (
                input("Kill the affiliated processus (y/n) ? : ")
                if not args.assume_yes and not args.assume_no
                else ("y" if args.assume_yes else "n")
            )

            if choice == "y":
                with open(pid_file_path, "r") as fd:
                    os.kill(int(fd.read()), signal.SIGTERM)

                while 1:
                    if isPortBindable(self.config_content["server"].get("listen_port")):
                        break

                    time.sleep(1)

            self.__log_stdout("", bypass=args.json)

        if args.d:
            if args.json:
                if args.enable_stdout_log:
                    self.__log_json(
                        LOG_JSON_STATUS_SUCCESS,
                        "Direct execution mode enabled, use CTRL+C to stop the server.",
                    )

            else:
                if args.enable_stdout_log:
                    self.__log_stdout(
                        "Direct execution mode enabled, use CTRL+C to stop the server.\n",
                    )

            launchServerProcess(
                self.config_content,
                enable_stdout_log=args.enable_stdout_log,
                enable_traceback_on_log=args.enable_traceback_log,
            )

        else:
            if args.json:
                self.__log_json(
                    LOG_JSON_STATUS_SUCCESS,
                    "Server is starting",
                )

            else:
                self.__log_stdout("Server is starting")

            # https://pypi.org/project/python-daemon/
            with daemon.DaemonContext(
                uid=pwd.getpwnam(self.config_content["server"].get("user")).pw_uid,
                gid=pwd.getpwnam(self.config_content["server"].get("user")).pw_gid,
                pidfile=daemon.pidfile.PIDLockFile(pid_file_path),
            ):
                launchServerProcess(self.config_content)

        return 0

    def stop(self):
        parser = argparse.ArgumentParser(
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description="""\033[1m-> Stop the server\033[0m

Sends a SIGINT signal to the server daemon to stop it.""",
            usage=f"{sys.argv[0]} stop [OPT]",
        )
        parser.add_argument(
            "--json", help="print output in JSON format", action="store_true"
        )
        args = parser.parse_args(sys.argv[2:])

        self.json = args.json
        pid_file_path = self.config_content["server"].get("pid_file_path")

        if not os.path.exists(pid_file_path):
            if args.json:
                self.__log_json(LOG_JSON_STATUS_SUCCESS, "Server is already stopped")

            else:
                self.__log_stdout("Server is already stopped\n", color=Colors.RED)

            return 0

        with open(pid_file_path, "r") as fd:
            os.kill(int(fd.read()), signal.SIGTERM)

        if args.json:
            self.__log_json(LOG_JSON_STATUS_SUCCESS, "Server is stopped")

        return 0

    def restart(self):
        parser = argparse.ArgumentParser(
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description="\033[1m-> Restart the server\033[0m",
            usage=f"{sys.argv[0]} restart [OPT]",
        )
        parser.add_argument(
            "--json", help="print output in JSON format", action="store_true"
        )
        args = parser.parse_args(sys.argv[2:])

        self.json = args.json
        pid_file_path = self.config_content["server"].get("pid_file_path")

        if not os.path.exists(pid_file_path):
            if args.json:
                self.__log_json(LOG_JSON_STATUS_SUCCESS, "Server is already stopped")

            else:
                self.__log_stdout("Server is already stopped\n")

            return 0

        with open(pid_file_path, "r") as fd:
            os.kill(int(fd.read()), signal.SIGTERM)

            while 1:
                if isPortBindable(self.config_content["server"].get("listen_port")):
                    break

                time.sleep(1)

        if args.json:
            self.__log_json(LOG_JSON_STATUS_SUCCESS, "Server is started")

        with daemon.DaemonContext(
            uid=pwd.getpwnam(self.config_content["server"].get("user")).pw_uid,
            gid=pwd.getpwnam(self.config_content["server"].get("user")).pw_gid,
            pidfile=daemon.pidfile.PIDLockFile(pid_file_path),
        ):
            launchServerProcess(self.config_content)

        return 0

    def access_tk(self):
        parser = argparse.ArgumentParser(
            formatter_class=argparse.RawDescriptionHelpFormatter,
            description="""\033[1m-> Manage access tokens\033[0m""",
            usage=f"{sys.argv[0]} access-tk [OPT]",
        )
        parser.add_argument("-a", help="add a new token entry", action="store_true")
        parser.add_argument("-l", help="list token entries", action="store_true")
        parser.add_argument(
            "-r",
            help="delete a token",
            dest="delete_entry",
            metavar="ENTRY_ID",
            type=int,
        )
        parser.add_argument(
            "-e",
            help="enable a token",
            dest="enable_entry",
            metavar="ENTRY_ID",
            type=int,
        )
        parser.add_argument(
            "-d",
            help="disable a token",
            dest="disable_entry",
            metavar="ENTRY_ID",
            type=int,
        )
        parser.add_argument(
            "--disabled",
            help="disable the created access token by default",
            action="store_true",
        )
        parser.add_argument(
            "--json", help="print output in JSON format", action="store_true"
        )
        args = parser.parse_args(sys.argv[2:])

        self.json = args.json
        access_tokens_database_file_path = self.config_content["access_token"].get(
            "access_tokens_database_file_path"
        )

        if not os.path.exists(access_tokens_database_file_path):
            createFileRecursively(access_tokens_database_file_path)

        access_token_manager = AccessTokenManager(access_tokens_database_file_path)

        if args.a:
            new_entry_tuple = access_token_manager.addEntry(
                disable=True if args.disabled else False
            )

            if args.json:
                self.__log_json(
                    LOG_JSON_STATUS_SUCCESS,
                    "New access token created",
                    data={
                        "entry_id": new_entry_tuple[0],
                        "access_token": new_entry_tuple[2],
                    },
                )

                return 0

            self.__log_stdout("New access token created", color=Colors.GREEN)
            self.__log_stdout(f"Entry ID : {new_entry_tuple[0]}")
            self.__log_stdout(f"   Token : {new_entry_tuple[2]}\n")

        elif args.l:
            if args.json:
                entry_list = access_token_manager.listEntries()

                self.__log_json(
                    LOG_JSON_STATUS_SUCCESS,
                    "Recorded entries ID",
                    data={"entry_list": entry_list},
                )

                return 0

            for (
                entry_id,
                creation_timestamp,
                enabled,
            ) in access_token_manager.listEntries():
                self.__log_stdout(f"- Entry ID {entry_id}")
                self.__log_stdout(
                    f"Created : {datetime.fromtimestamp(creation_timestamp)}"
                )
                self.__log_stdout(f"Enabled : {bool(enabled)}\n")

        else:
            if args.delete_entry:
                if not access_token_manager.getEntry(args.delete_entry):
                    if args.json:
                        self.__log_json(
                            LOG_JSON_STATUS_ERROR,
                            f"Entry ID {args.delete_entry} does not exists on database",
                        )

                    else:
                        self.__log_stdout(
                            f"Entry ID {args.delete_entry} does not exists on database\n",
                            color=Colors.RED,
                        )

                    return 0

                access_token_manager.deleteEntry(args.delete_entry)

                if args.json:
                    self.__log_json(LOG_JSON_STATUS_SUCCESS, "Entry ID was deleted")
                    return 0

            elif args.enable_entry:
                if not access_token_manager.getEntry(args.enable_entry):
                    if args.json:
                        self.__log_json(
                            LOG_JSON_STATUS_ERROR,
                            f"Entry ID {args.enable_entry} does not exists on database",
                        )

                    else:
                        self.__log_stdout(
                            f"Entry ID {args.enable_entry} does not exists on database\n",
                            color=Colors.RED,
                        )

                    return 0

                access_token_manager.enableEntry(args.enable_entry)

                if args.json:
                    self.__log_json(LOG_JSON_STATUS_SUCCESS, "Entry ID was enabled")
                    return 0

            else:
                if args.disable_entry:
                    if not access_token_manager.getEntry(args.disable_entry):
                        if args.json:
                            self.__log_json(
                                LOG_JSON_STATUS_ERROR,
                                f"Entry ID {args.disable_entry} does not exists on database",
                            )

                        else:
                            self.__log_stdout(
                                f"Entry ID {args.disable_entry} does not exists on database\n",
                                color=Colors.RED,
                            )

                        return 0

                    access_token_manager.disableEntry(args.disable_entry)

                    if args.json:
                        self.__log_json(
                            LOG_JSON_STATUS_SUCCESS, "Entry ID was disabled"
                        )
                        return 0

        access_token_manager.closeDatabase()
        return 0

    def regen_rsa(self):
        parser = argparse.ArgumentParser(
            description="\033[1m-> Regenerate RSA keys\033[0m",
            usage=f"{sys.argv[0]} regen-rsa [OPT]",
        )
        parser.add_argument(
            "-b",
            help=f"specify the key size, in bytes (default is {DEFAULT_RSA_KEY_SIZE})",
            dest="key_size",
            type=int,
        )
        parser.add_argument(
            "--json", help="print output in JSON format", action="store_true"
        )
        args = parser.parse_args(sys.argv[2:])

        self.json = args.json

        new_rsa_wrapper = RSAWrapper(
            key_size=args.key_size if args.key_size else DEFAULT_RSA_KEY_SIZE
        )

        public_key_path = self.config_content["server"].get("public_rsa_key_file_path")
        private_key_path = self.config_content["server"].get(
            "private_rsa_key_file_path"
        )

        if not os.path.exists(public_key_path):
            createFileRecursively(public_key_path)

        if not os.path.exists(private_key_path):
            createFileRecursively(private_key_path)

        with open(public_key_path, "w") as fd:
            fd.write(new_rsa_wrapper.getPublicKey().decode())

        with open(private_key_path, "w") as fd:
            fd.write(new_rsa_wrapper.getPrivateKey().decode())

        if args.json:
            self.__log_json(
                LOG_JSON_STATUS_SUCCESS,
                "RSA keys re-generated",
                data={
                    "fingerprint": hashlib.sha256(
                        new_rsa_wrapper.getPublicKey()
                    ).hexdigest()
                },
            )

        else:
            self.__log_stdout("RSA keys re-generated", color=Colors.GREEN)
            self.__log_stdout(
                f"Fingerprint : {hashlib.sha256(new_rsa_wrapper.getPublicKey()).hexdigest()}\n"
            )

        return 0
