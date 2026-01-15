"use client";

import { useContext, useEffect } from "react";
import { useRouter } from "next/navigation";

import UserContext from "../../contexts/user";

export default function AdminPage() {
  const router = useRouter();
  const currentUser = useContext(UserContext);

  useEffect(() => {
    if (currentUser) {
      if (currentUser.is_superuser) {
        router.replace("/admin/system/users");
      } else {
        router.replace("/");
      }
    }
  }, [currentUser, router]);

  return null;
}
