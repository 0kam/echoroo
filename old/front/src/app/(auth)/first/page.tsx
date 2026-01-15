"use client";

import { useRouter } from "next/navigation";
import { useCallback } from "react";
import toast from "react-hot-toast";

import { EchorooIcon } from "@/lib/components/icons";
import Info from "@/lib/components/ui/Info";
import UserCreateForm from "@/lib/components/users/UserCreateForm";

import type { User } from "@/lib/types";

export default function Page() {
  const router = useRouter();

  const handleCreate = useCallback(
    (user: Promise<User>) => {
      toast.promise(
        user.then((user) => {
          router.push("/login");
          return user;
        }),
        {
          loading: "Creating account...",
          success: "Account created!",
          error: "Failed to create account",
        },
      );
    },
    [router],
  );

  const handleAuthenticationError = useCallback(() => {
    toast.error("This is not your first time here, is it?");
    router.push("/login");
  }, [router]);

  return (
    <div className="flex flex-col items-center justify-center min-h-screen">
      <div className="flex flex-col w-full max-w-4xl gap-8 px-4 py-10">
        <div className="flex flex-col items-center gap-4 text-center text-7xl">
          <EchorooIcon width={128} height={128} />
          <span className="font-sans font-bold text-emerald-500 underline decoration-8">
            Echoroo
          </span>
        </div>
        <section className="flex flex-col gap-4">
          <h1 className="text-3xl font-bold text-center">Welcome!</h1>
          <p className="max-w-prose mx-auto text-center text-stone-600 dark:text-stone-300">
            Let&apos;s get started by creating your administrator account.
          </p>
          <Info className="max-w-prose mx-auto">
            <p className="text-sm text-stone-600 dark:text-stone-300">
              <strong>Note:</strong> Audio directory configuration is now done through
              environment variables. Please ensure <code>WHOMBAT_AUDIO_DIR</code> is set
              in your <code>.env</code> file before starting Echoroo.
            </p>
          </Info>
        </section>

        <section className="rounded-xl border border-stone-200 bg-white p-6 shadow-sm dark:border-stone-700 dark:bg-stone-900">
          <h2 className="text-xl font-semibold text-stone-800 dark:text-stone-100">
            Create your administrator account
          </h2>
          <p className="mt-2 text-sm text-stone-600 dark:text-stone-300">
            Provide your information and choose a secure password. You can add
            more users later from the administration page.
          </p>
          <div className="mt-6">
            <UserCreateForm
              onCreate={handleCreate}
              onAuthenticationError={handleAuthenticationError}
            />
          </div>
          <Info className="mt-4">
            <p className="text-sm text-stone-600 dark:text-stone-300">
              Your data stays on this machine. Echoroo does not send recordings
              or metadata to external servers.
            </p>
          </Info>
        </section>
      </div>
    </div>
  );
}
