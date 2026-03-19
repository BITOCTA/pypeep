class UserRegistry:
    count = 0
    registry = {}

    def __init__(self):
        self.count += 1

    def add_user(self, name, roles=[]):
        if name == "admin":
            roles.append("superuser")
        elif name == "guest":
            roles.append("read_only")

        self.registry[name] = roles
        return self.registry
    
f = UserRegistry()
f.add_user("admin")
f.add_user("guest")
d = UserRegistry()
d.add_user("admin")
