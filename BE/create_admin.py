from database import create_user

username = input("Username: ")
password = input("Password: ")
create_user(username, password)
print(f"User '{username}' berhasil dibuat.")