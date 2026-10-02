from __future__ import annotations

import sys

from .setup import SetupWizard
from .setup.wizard import Step


def main() -> None:
    wizard = SetupWizard()
    print(wizard.start())
    while wizard.step != Step.DONE:
        try:
            line = input("\n[voce] ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n\nEncerrado.")
            break
        if not line:
            continue
        reply = wizard.handle(line)
        print(f"\n[assistente]\n{reply}")


if __name__ == "__main__":
    main()
    sys.exit(0)
