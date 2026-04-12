@echo off
cd c:\projects\DeadlockSim
python -m pytest tests/ -x -v --timeout=120
