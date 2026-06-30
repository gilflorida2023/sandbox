package main

import (
    "crypto/sha256"
    "encoding/hex"
    "fmt"
    "math"
)

func isPrime(n int) bool {
    if n <= 1 {
        return false
    }
    for i := 2; i <= int(math.Sqrt(float64(n))); i++ {
        if n%i == 0 {
            return false
        }
    }
    return true
}

func main() {
    limit := 1000000
    var primeString string

    for number := 2; number <= limit; number++ {
        if isPrime(number) {
            primeString += fmt.Sprintf("%d\n", number)
        }
    }

    hash := sha256.Sum256([]byte(primeString))
    fmt.Println(hex.EncodeToString(hash[:]))
}
