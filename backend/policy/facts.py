"""Facts are typed values, not sentences: the UI and the draft turn them into words."""

import datetime as dt
from decimal import Decimal

type Fact = Decimal | dt.date | bool | int | str | list[str]
