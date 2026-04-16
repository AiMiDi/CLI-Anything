"""Small REPL skin used by cli-anything-nsight-graphics."""

from __future__ import annotations

from pathlib import Path


class ReplSkin:
    """Minimal REPL helper with lightweight styling."""

    def __init__(self, software: str, version: str = "0.1.0"):
        self.software = software
        self.version = version
        self.history_file = str(Path.home() / f".cli-anything-{software}" / "history")
        Path(self.history_file).parent.mkdir(parents=True, exist_ok=True)
        skill_path = Path(__file__).resolve().parent.parent / "skills" / "SKILL.md"
        self.skill_path = str(skill_path) if skill_path.is_file() else None

    def print_banner(self) -> None:
        print(f"cli-anything · {self.software} v{self.version}")
        if self.skill_path:
            print(f"Skill: {self.skill_path}")
        print("Type help for commands, quit to exit.\n")

    def create_prompt_session(self):
        try:
            from prompt_toolkit import PromptSession
            from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
            from prompt_toolkit.history import FileHistory

            return PromptSession(
                history=FileHistory(self.history_file),
                auto_suggest=AutoSuggestFromHistory(),
                enable_history_search=True,
            )
        except ImportError:
            return None

    def get_input(self, session, project_name: str = "", modified: bool = False) -> str:
        suffix = f"[{project_name}]" if project_name else ""
        prompt = f"{self.software}{suffix}> "
        if session is None:
            return input(prompt).strip()
        return session.prompt(prompt).strip()

    def help(self, commands: dict[str, str]) -> None:
        print("Commands:")
        for name, description in commands.items():
            print(f"  {name:<14} {description}")
        print()

    def warning(self, message: str) -> None:
        print(f"[warn] {message}")

    def error(self, message: str) -> None:
        print(f"[error] {message}")

    def print_goodbye(self) -> None:
        print("\nGoodbye.\n")
