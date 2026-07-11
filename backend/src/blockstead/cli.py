import argparse

from .config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(prog="blockstead")
    parser.add_argument("command", choices=["validate-config"])
    parser.parse_args()
    settings = Settings()
    settings.prepare()
    print(f"Configuration valid. Binding to {settings.bind_host}:{settings.port}.")


if __name__ == "__main__":
    main()
