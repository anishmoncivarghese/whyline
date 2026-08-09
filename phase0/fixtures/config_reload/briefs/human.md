Parse the entire configuration into a new dictionary and validate it before touching live state. Then swap the dictionary under the existing lock. Split each line only on the first equals sign because values may contain equals.

