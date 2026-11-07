from __future__ import annotations
from dataclasses import dataclass
from ortools.sat.python import cp_model
from models import Task, Config


@dataclass
class Chunk:
    used: cp_model.IntVar
    start: cp_model.IntVar
    length: cp_model.IntVar
    end: cp_model.IntVar
    day: cp_model.IntVar


@dataclass
class Ctx:
    tasks: list[Task]
    cfg: Config
    present: dict
    chunks: dict
    finish: dict