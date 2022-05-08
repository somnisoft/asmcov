# asmcov
Measure coverage of assembly instructions in ELF executable using ptrace.

## Known limitations
* Only measures line coverage
* Does not work on binaries compiled as shared object files
* Requires x86\_64 ELF executable running on Linux
* Very slow execution

## Usage
```shell
# Compile ptrace interface used by asmcov.py
make

# Run the binary one or more times to collect statistics
./asmcov.py /path/to/bin
./asmcov.py /path/to/bin arg1
./asmcov.py /path/to/bin arg1 arg2

# Generate a report (asmcov.html) and open in default web browser
./asmcov.py -r /path/to/bin

# Report highlights the instructions that did not execute
# Report also includes number of times each line hit
```
