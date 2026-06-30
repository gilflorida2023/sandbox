#include <stdio.h>
#include <stdbool.h>

int main() {
    int n = 100;
    bool prime[n + 1];
    for (int i = 0; i <= n; i++)
        prime[i] = true;

    for (int p = 2; p * p <= n; p++) {
        if (prime[p]) {
            for (int i = p * p; i <= n; i += p)
                prime[i] = false;
        }
    }

    FILE *file = fopen("out.txt", "w");
    for (int p = 2; p <= n; p++)
        if (prime[p])
            fprintf(file, "%d\n", p);
    fclose(file);
    return 0;

}