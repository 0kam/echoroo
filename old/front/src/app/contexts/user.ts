import { createContext } from "react";

import type { User } from "@/lib/types";

const UserContext = createContext<User>({
  id: "",
  username: "",
  email: "",
  is_superuser: false,
  is_active: false,
  is_verified: false,
});

export default UserContext;
