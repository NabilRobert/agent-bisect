"""The planted-fault benchmark set (slice 3a), built in four steps:

1. `tasks.py`: keep the tasks the agent passes from scratch (`f(0) ≤ 0.2`);
2. `plant.py`: one clean passing run per kept task, and a fault plan per
   fault type and position;
3. `effective.py`: probes on either side of each fault; an effective fault
   is kept with one failing continuation as its "bad run";
4. `frozen.py`: everything written under `bench/frozen/<agent>/` with a
   fingerprint, committed before any method is scored.
"""
