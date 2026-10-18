"""The common shape every identifier returns, so tools and the UI treat all entities alike."""
from dataclasses import dataclass, field, asdict

HIGH, MEDIUM, LOW = "high", "medium", "low"


@dataclass
class Candidate:
    value: str            # canonical value: "LN00123", "Barmer", a customer id
    label: str = ""       # what to say back: "Barmer, Rajasthan"
    distance: float = 0.0


@dataclass
class EntityResult:
    kind: str                       # name, dob, phone, loan_id, district, amount, ...
    heard: str                      # exactly what STT gave us
    value: str | None               # normalised value, None if not understood
    confidence: str                 # high / medium / low
    normalised: str = ""            # intermediate form (romanised text, digit string)
    candidates: list[Candidate] = field(default_factory=list)
    issues: list[str] = field(default_factory=list)

    @property
    def action(self) -> str:
        """What the agent should do next with this value."""
        if self.value is None or self.confidence == LOW:
            return "ask_again"
        if self.confidence == MEDIUM:
            return "read_back"
        return "accept"

    def to_dict(self) -> dict:
        d = asdict(self)
        d["action"] = self.action
        return d
