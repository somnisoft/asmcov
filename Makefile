.POSIX:
.PHONY: all clean

all: asmcovtrace.so

asmcovtrace.so: asmcovtrace.c
	cc -shared -fpic -o $@ $<

clean:
	rm -f asmcov.db asmcov.html asmcovtrace.so
