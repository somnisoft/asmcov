/**
 * @file
 * @brief asmcovtrace - ptrace interface for asmcov.py
 *
 * SPDX-License-Identifier: CC0-1.0
 */

#include <sys/ptrace.h>
#include <sys/types.h>
#include <sys/user.h>
#include <sys/wait.h>
#include <err.h>
#include <errno.h>
#include <unistd.h>

pid_t
asmcovtrace_open(
	const char *const path,
	char *const argv[]
);

unsigned long long
asmcovtrace_next(
	const pid_t pid
);

pid_t
asmcovtrace_open(
	const char *const path,
	char *const argv[]
){
	pid_t pid;

	pid = fork();
	if(pid == -1){
		err(1, "fork");
	}
	else if(pid == 0){
		if(ptrace(PTRACE_TRACEME, 0, NULL, NULL) == -1){
			err(1, "ptrace");
		}
		execve(path, argv, NULL);
		err(1, "exec: %s", path);
	}
	return pid;
}

unsigned long long
asmcovtrace_next(
	const pid_t pid
){
	struct user_regs_struct regs;
	int status;

	wait(&status);
	if(WIFEXITED(status)){
		return WEXITSTATUS(status);
	}
	errno = 0;
	if(ptrace(PTRACE_GETREGS, pid, NULL, &regs) == -1 ||
	   ptrace(PTRACE_SINGLESTEP, pid, NULL, NULL) == -1){
		if(errno == ESRCH){
			return 0;
		}
		err(1, "ptrace: %d", errno);
	}
	return regs.rip;
}
