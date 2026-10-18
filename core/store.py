"""
The NBFC "system of record" for the demo: the generated CSVs loaded into
memory, plus the few things calls can create (tickets, service requests,
case notes, priority changes, escalations).

Writes live in memory for the life of the process and are capped, so a
public demo cannot grow memory without bound. A real deployment would put
a database behind the same methods.
"""
import csv
import hashlib
import itertools
import threading
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

MAX_TOTAL_WRITES = 10_000


@dataclass
class Store:
    customers: dict[str, dict]
    loans: dict[str, dict]
    emis: dict[str, list[dict]]
    tickets: dict[str, dict]
    staff: dict[str, dict]
    branches: dict[str, dict]
    today: date
    notes: dict[str, list[dict]] = field(default_factory=lambda: defaultdict(list))
    requests: list[dict] = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _writes: int = 0
    _ticket_seq: itertools.count = field(default_factory=lambda: itertools.count(200_001))
    _request_seq: itertools.count = field(default_factory=lambda: itertools.count(1))

    # ---- loading -------------------------------------------------------------

    @classmethod
    def load(cls, data_dir: Path, today: date) -> "Store":
        def rows(name: str) -> list[dict]:
            with open(data_dir / name, encoding="utf-8") as f:
                return list(csv.DictReader(f))

        emis: dict[str, list[dict]] = defaultdict(list)
        for e in rows("emi_schedule.csv"):
            emis[e["loan_id"]].append(e)
        return cls(
            customers={c["customer_id"]: c for c in rows("customers.csv")},
            loans={l["loan_id"]: l for l in rows("loans.csv")},
            emis=dict(emis),
            tickets={t["ticket_id"]: t for t in rows("tickets.csv")},
            staff={s["employee_id"]: s for s in rows("staff.csv")},
            branches={b["branch_code"]: b for b in rows("branches.csv")},
            today=today,
        )

    # ---- reads -----------------------------------------------------------------

    def people(self) -> list[tuple[str, str]]:
        return [(c["customer_id"], c["full_name"]) for c in self.customers.values()]

    def customers_with(self, field_name: str, value: str) -> list[dict]:
        return [c for c in self.customers.values() if c.get(field_name) == value]

    def loans_of(self, customer_id: str) -> list[dict]:
        return [l for l in self.loans.values() if l["customer_id"] == customer_id]

    def tickets_of(self, customer_id: str) -> list[dict]:
        return sorted((t for t in self.tickets.values() if t["customer_id"] == customer_id),
                      key=lambda t: t["created_on"], reverse=True)

    def branch_for_district(self, district: str, state: str) -> dict | None:
        return next((b for b in self.branches.values() if b["district"] == district and b["state"] == state), None)

    # ---- writes ----------------------------------------------------------------

    def _count_write(self) -> None:
        if self._writes >= MAX_TOTAL_WRITES:
            raise RuntimeError("demo write limit reached; restart the server to reset")
        self._writes += 1

    def add_ticket(self, customer_id: str, loan_id: str | None, kind: str, summary: str) -> dict:
        with self._lock:
            self._count_write()
            tid = f"TK{next(self._ticket_seq):06d}"
            t = {"ticket_id": tid, "customer_id": customer_id, "loan_id": loan_id or "", "type": kind,
                 "summary": summary[:300], "status": "open", "created_on": self.today.isoformat(),
                 "updated_on": self.today.isoformat(), "follow_ups": 0}
            self.tickets[tid] = t
            return t

    def add_request(self, customer_id: str | None, loan_id: str | None, kind: str, details: str, by: str) -> dict:
        with self._lock:
            self._count_write()
            r = {"request_id": f"SR{next(self._request_seq):05d}", "customer_id": customer_id, "loan_id": loan_id,
                 "type": kind, "details": details[:300], "created_by": by, "created_on": self.today.isoformat()}
            self.requests.append(r)
            return r

    def add_note(self, loan_id: str, text: str, by: str) -> dict:
        with self._lock:
            self._count_write()
            n = {"loan_id": loan_id, "text": text[:600], "by": by, "on": self.today.isoformat()}
            self.notes[loan_id].append(n)
            return n

    def set_priority(self, loan_id: str, priority: str, by: str, reason: str) -> dict:
        with self._lock:
            self._count_write()
            self.loans[loan_id]["priority"] = priority
            n = {"loan_id": loan_id, "text": f"Priority set to {priority}: {reason[:300]}", "by": by, "on": self.today.isoformat()}
            self.notes[loan_id].append(n)
            return n

    def bureau_retry(self, loan_id: str) -> bool:
        """Mock bureau pull: deterministic per loan, so demos are repeatable."""
        with self._lock:
            self._count_write()
            ok = hashlib.sha256(loan_id.encode()).digest()[0] % 3 != 0
            if ok and self.loans[loan_id]["stage"] == "Credit_Check":
                self.loans[loan_id]["internal_note"] = "Bureau pull succeeded on retry; awaiting credit decision"
                self.loans[loan_id]["customer_message"] = "Your credit check is complete and a decision is being made."
            return ok
