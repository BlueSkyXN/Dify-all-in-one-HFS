#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>

/*
 * The Space image stays rootless. This root-owned, setuid launcher is created
 * at image build time so the manifest-installed sandbox server can retain the
 * upstream privilege boundary without granting the bootstrap root access.
 */
int main(int argc, char *argv[]) {
    (void)argc;
    const char *target = "/opt/dify/runtime/opt/dify/sandbox/main";
    if (access(target, X_OK) != 0) {
        fprintf(stderr, "Dify sandbox artifact executable is unavailable: %s\n", target);
        return 126;
    }
    if (setgid(0) != 0 || setuid(0) != 0) {
        perror("Dify sandbox launcher cannot acquire required privileges");
        return 126;
    }
    execv(target, argv);
    perror("Dify sandbox launcher cannot execute artifact");
    return errno == ENOENT ? 127 : 126;
}
