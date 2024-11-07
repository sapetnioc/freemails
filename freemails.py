import email
import fnmatch
import getpass
import imaplib
import pathlib
import pickle
import re
import sys


class MailBox:
    def __init__(self):
        self._config = None

    @property
    def config(self):
        if self._config is None:
            self._config = self._read_config()
        return self._config

    def _read_config(self):
        config_file = pathlib.Path.home() / ".config" / "freemails"
        if config_file.exists():
            with open(config_file, "rb") as f:
                return pickle.load(f)
        return {}

    def write_config(self):
        config_file = pathlib.Path.home() / ".config" / "freemails"
        with open(config_file, "wb") as f:
            pickle.dump(self._config or {}, f)

    def __enter__(self):
        # self.mailbox = imaplib.IMAP4_SSL("imap.gmail.com")
        # self.mailbox.login(gl, gp)
        self.mailbox = imaplib.IMAP4_SSL(self.config["server"])
        self.mailbox.login(self.config["login"], self.config["password"])
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.mailbox.close()
        self.mailbox.logout()

    def iter_directories(self):
        for m in (i.split(b' "/" ', 1)[1].decode() for i in self.mailbox.list()[1]):
            if m in {
                '"Bo&AO4-te d\'envoi"',
                "Calendrier",
                '"&AMk-l&AOk-ments supprim&AOk-s"',
                "Journal",
                "Notes",
                "T&AOI-ches",
                '"&AMk-l&AOk-ments envoy&AOk-s"',
                '"Courrier ind&AOk-sirable"',
                "Contacts",
                "Calendrier/basic",
                "Brouillons",
            }:
                continue
            yield m

    def select(self, directory):
        self.directory = directory
        return int(self.mailbox.select(directory)[1][0])

    def search(self, *args):
        if not args:
            args = ("ALL",)
        yield from self.mailbox.search(None, *args)[1][0].split()

    def fetch(self, message_number):
        data, flags = self.mailbox.fetch(message_number, "(RFC822)")[1]
        return email.message_from_bytes(data[1])

    def filter(self, message):
        from_ = message["From"]
        m = re.match(r"[^<]*<([^>]*)>", from_)
        if m:
            from_ = m.group(1)
        subject = message["Subject"]
        black_from = self.config.get("black_from", set())
        white_from = self.config.get("white_from", set())
        black_subject = self.config.get("black_subject", set())
        white_subject = self.config.get("white_subject", set())
        if from_ in black_from:
            return (False, f"sender in black_from")
        if subject in black_subject:
            return (False, f"subject in black_subject")
        if from_ in white_from:
            return (True, f"sender in white_from")
        if subject in white_subject:
            return (True, f"subject in white_subject")
        for filter in white_from:
            if self.match_filter(from_, filter):
                return (True, "sender match white_from filter")
        for filter in white_subject:
            if self.match_filter(subject, filter):
                return (True, "subject match white_subject filter")
        return (False, "default rule")

    @staticmethod
    def match_filter(string, filter):
        inverted = False
        if filter.startswith("~"):
            inverted = True
            filter = filter[1:]
        match = fnmatch.fnmatch(string, filter)
        if inverted:
            match = not match
        return match


def main():
    args = sys.argv[1:]
    mailbox = MailBox()
    if not args:
        args = ("config",)
    config_modified = False
    for i in args:
        eq_index = i.find("=")
        if eq_index >= 0:
            name = i[:eq_index]
            value = i[eq_index + 1 :]
            if name == "password" and not value:
                value = getpass.getpass()
            add_remove = None
            if name and name[0] in ("+", "-"):
                add_remove = name[0]
                name = name[1:]
            if name in {
                "white_from",
                "black_from",
                "white_subject",
                "black_subject",
                "white_dir",
                "black_dir",
            }:
                if not add_remove:
                    print(f"{name} is a list, use + or - to modify it", file=sys.stderr)
                    sys.exit(1)
            elif name not in {"server", "login", "password"}:
                print("Unknown config item:", name, file=sys.stderr)
                sys.exit(1)
            if add_remove == "+":
                s = mailbox.config.setdefault(name, set())
                s.add(value)
            elif add_remove == "-":
                s = mailbox.config.setdefault(name, set())
                s.remove(value)
            else:
                mailbox.config[name] = value
            config_modified = True
        elif i == "password":
            mailbox.config["password"] = getpass.getpass()
            config_modified = True
        elif i in {"-h", "--help", "help"}:
            print(f"Usage: freemails [[+|-]<config_item>=<value>...] [<command>...]")
            print("Commands:")
            print("    config : show configuration (default if no command is given)")
            print('    list : list "From" and "Object" of all messages')
        elif i.startswith("-"):
            del mailbox.config[i[1:]]
            config_modified = True
        elif i == "config":
            if not mailbox.config:
                print("No configuration")
            else:
                for name, value in mailbox.config.items():
                    if name == "password":
                        value = "..."
                    print(name, "=", value)
        elif i == "list":
            with mailbox:
                for directory in mailbox.iter_directories():
                    count = mailbox.select(directory)
                    print("=" * 30, directory, ":", count, "=" * 30)
                    if directory in mailbox.config.get("black_dir", set()):
                        print("  All locked because directory in black_dir")
                        continue
                    if directory in mailbox.config.get("white_dir", set()):
                        print("  All freed because directory in white_dir")
                        continue
                    message_numbers = mailbox.search()
                    for message_number in message_numbers:
                        msg = mailbox.fetch(message_number)
                        decision, explanation = mailbox.filter(msg)
                        print(msg["From"], ":", msg["Subject"])
                        print(
                            " ",
                            ("freed" if decision else "locked"),
                            "because",
                            explanation,
                        )
        else:
            print("Unknown command:", i, file=sys.stderr)
            sys.exit(1)

    if config_modified:
        mailbox.write_config()
