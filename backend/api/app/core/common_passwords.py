"""Very common passwords of 8+ characters, which the policy rejects (compared case-insensitively).

Drawn from widely published "most common passwords" lists. Shorter ones aren't listed because
the length minimum already rejects them. Simple repeats and keyboard or alphabet sequences are
caught separately in app/core/passwords.py. A larger offline breached-password list can replace
this later without changing callers.
"""

COMMON_PASSWORDS = frozenset(
    {
        "password", "password1", "password12", "password123", "password1234", "passw0rd",
        "p@ssw0rd", "p@ssword", "pa$$word", "passwort", "motdepasse", "contraseña",
        "12345678", "123456789", "1234567890", "0987654321", "87654321", "11223344",
        "12341234", "12121212", "11111111", "00000000", "88888888", "99999999", "123123123",
        "12344321", "147258369", "123456780", "1q2w3e4r", "1q2w3e4r5t", "1qaz2wsx", "qazwsxedc",
        "zaq12wsx", "q1w2e3r4", "q1w2e3r4t5", "qwerty12", "qwerty123", "qwerty1234",
        "qwertyuiop", "asdfghjkl", "zxcvbnm1", "abc12345", "abcd1234", "abcdefgh", "a1b2c3d4",
        "aa123456", "iloveyou", "iloveyou1", "iloveyou2", "loveyou1", "sunshine", "sunshine1",
        "princess", "princess1", "football", "football1", "baseball", "basketball", "soccer12",
        "liverpool", "chelsea1", "arsenal1", "manchester", "barcelona", "superman", "batman123",
        "spiderman", "starwars", "pokemon1", "minecraft", "fortnite", "roblox123", "welcome1",
        "welcome123", "letmein1", "letmein123", "trustno1", "whatever", "computer", "internet",
        "michelle", "jennifer", "jessica1", "charlie1", "danielle", "jordan23", "michael1",
        "samantha", "alexander", "elizabeth", "christopher", "nicholas", "babygirl", "butterfly",
        "chocolate", "cookie123", "monkey123", "dragon123", "shadow123", "master123", "killer123",
        "freedom1", "blessed1", "jesus123", "godisgood", "blessing", "lovely123", "flower123",
        "passport", "changeme", "changeme1", "default1", "secret123", "admin123", "admin1234",
        "administrator", "adminadmin", "rootroot", "test1234", "testtest", "guest123",
        "student1", "student123", "teacher1", "teacher123", "school123", "school1234",
        "exam1234", "password!", "password@1", "welcome@123", "india123", "nigeria1",
        "nigeria123", "lagos123", "london123", "summer2024", "summer2025", "summer2026",
        "winter2025", "spring2026", "january1", "september", "december", "monday123",
    }
)
