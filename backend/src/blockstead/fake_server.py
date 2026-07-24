import argparse
import sys
import time

PLAYER_LIMIT = 20


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode", choices=["normal", "slow", "ignore-stop", "crash"], default="normal"
    )
    mode = parser.parse_args().mode
    print("[Server thread/INFO]: Starting minecraft server fixture", flush=True)
    if mode == "slow":
        time.sleep(1)
    if mode == "crash":
        print("[Server thread/ERROR]: Fixture startup failed", flush=True)
        raise SystemExit(17)
    print('[Server thread/INFO]: Done (0.123s)! For help, type "help"', flush=True)
    whitelist: set[str] = {"Alex_Fixture", "Steve_Fixture"}
    operators: set[str] = {"Alex_Fixture"}
    banned: set[str] = set()
    online: set[str] = {"Alex_Fixture"}

    def info(message: str) -> None:
        print(f"[Server thread/INFO]: {message}", flush=True)

    for line in sys.stdin:
        command = line.rstrip("\r\n")
        info(f"Received command: {command}")
        words = command.split()
        name = words[-1] if len(words) > 1 else ""
        if command == "stop" and mode != "ignore-stop":
            info("Stopping server")
            return
        if command == "list":
            info(
                f"There are {len(online)} of a max of {PLAYER_LIMIT} players online: "
                + ", ".join(sorted(online))
            )
        elif words[:2] == ["whitelist", "list"]:
            info(
                f"There are {len(whitelist)} whitelisted player(s): " + ", ".join(sorted(whitelist))
            )
        elif words[:2] == ["whitelist", "add"] and name:
            info(
                f"{name} is already whitelisted"
                if name in whitelist
                else f"Added {name} to the whitelist"
            )
            whitelist.add(name)
        elif words[:2] == ["whitelist", "remove"] and name:
            info(
                f"Removed {name} from the whitelist"
                if name in whitelist
                else f"{name} is not whitelisted"
            )
            whitelist.discard(name)
        elif words[:1] == ["op"] and name:
            operators.add(name)
            info(f"Made {name} a server operator")
        elif words[:1] == ["deop"] and name:
            operators.discard(name)
            info(f"Made {name} no longer a server operator")
        elif words[:1] == ["ban"] and name:
            banned.add(name)
            if name in online:
                online.discard(name)
                info(f"{name} left the game")
            info(f"Banned {name}: Banned by an operator")
        elif words[:1] == ["pardon"] and name:
            banned.discard(name)
            info(f"Unbanned {name}")
        elif words[:1] == ["kick"] and name:
            if name in online:
                online.discard(name)
                info(f"{name} left the game")
            info(f"Kicked {name}: Kicked by an operator")
        elif words[:1] == ["simulate-join"] and name:
            online.add(name)
            info(f"{name} joined the game")
        elif words[:1] == ["simulate-leave"] and name:
            online.discard(name)
            info(f"{name} left the game")
        elif words[:1] == ["say"]:
            info(f"[Server] {command[4:]}")


if __name__ == "__main__":
    main()
