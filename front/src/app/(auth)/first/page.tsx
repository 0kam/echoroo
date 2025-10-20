"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useCallback, useEffect } from "react";
import { useForm } from "react-hook-form";
import toast from "react-hot-toast";

import api from "@/app/api";

import { WhombatIcon } from "@/lib/components/icons";
import { Group, Input, Submit } from "@/lib/components/inputs";
import Info from "@/lib/components/ui/Info";
import UserCreateForm from "@/lib/components/users/UserCreateForm";

import { AudioDirectoryUpdateSchema } from "@/lib/schemas";
import type { AudioDirectoryUpdate, User } from "@/lib/types";

export default function Page() {
  const router = useRouter();

  const {
    data: audioDirectory,
    isLoading: isLoadingDirectory,
    refetch: refetchDirectory,
    isFetching: isRefreshingDirectory,
  } = useQuery({
    queryKey: ["setup", "audio_dir"],
    queryFn: api.setup.getAudioDirectory,
  });

  const {
    register,
    handleSubmit,
    reset,
    formState: { errors, isDirty },
  } = useForm<AudioDirectoryUpdate>({
    resolver: zodResolver(AudioDirectoryUpdateSchema),
    defaultValues: { audio_dir: "" },
  });

  useEffect(() => {
    if (!audioDirectory) return;
    reset({ audio_dir: audioDirectory.audio_dir });
  }, [audioDirectory, reset]);

  const { mutateAsync: saveDirectory, isPending: isSavingDirectory } =
    useMutation({
      mutationFn: api.setup.updateAudioDirectory,
      onSuccess: async (result) => {
        toast.success("Audio directory updated");
        reset(result);
        await refetchDirectory();
      },
      onError: (error: unknown) => {
        const message =
          (error as { response?: { data?: { detail?: string } } })?.response?.
            data?.detail ??
          (error instanceof Error ? error.message : undefined) ??
          "Failed to update audio directory";
        toast.error(message);
      },
    });

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

  const onSubmitDirectory = handleSubmit(async (payload) => {
    await saveDirectory(payload);
  });

  return (
    <div className="flex flex-col items-center justify-center min-h-screen">
      <div className="flex flex-col w-full max-w-4xl gap-8 px-4 py-10">
        <div className="flex flex-col items-center gap-4 text-center text-7xl">
          <WhombatIcon width={128} height={128} />
          <span className="font-sans font-bold text-emerald-500 underline decoration-8">
            Whombat
          </span>
        </div>
        <section className="flex flex-col gap-4">
          <h1 className="text-3xl font-bold text-center">Welcome!</h1>
          <p className="max-w-prose mx-auto text-center text-stone-600 dark:text-stone-300">
            Let&apos;s get started by configuring Whombat. First choose the root
            directory that stores your audio datasets, then create the initial
            administrator account.
          </p>
        </section>

        <section className="rounded-xl border border-stone-200 bg-white p-6 shadow-sm dark:border-stone-700 dark:bg-stone-900">
          <h2 className="text-xl font-semibold text-stone-800 dark:text-stone-100">
            Audio directory
          </h2>
          <p className="mt-2 text-sm text-stone-600 dark:text-stone-300">
            Whombat scans only the subdirectories of this path when registering
            datasets. The directory must already exist on disk.
          </p>
          <form className="mt-6 flex flex-col gap-4" onSubmit={onSubmitDirectory}>
            <Group
              name="audio_dir"
              label="Audio directory path"
              help="Absolute path to the folder containing your audio collections."
              error={errors.audio_dir?.message}
            >
              <Input
                {...register("audio_dir")}
                autoComplete="off"
                placeholder="/absolute/path/to/audio"
              />
            </Group>
            <div className="flex items-center gap-3">
              <Submit disabled={isSavingDirectory || (!isDirty && !isLoadingDirectory)}>
                {isSavingDirectory ? "Saving…" : "Save"}
              </Submit>
              <button
                type="button"
                onClick={() => void refetchDirectory()}
                className="text-sm text-amber-600 underline underline-offset-2 disabled:text-stone-400"
                disabled={isRefreshingDirectory}
              >
                {isRefreshingDirectory ? "Refreshing…" : "Reload"}
              </button>
            </div>
            <div className="text-sm text-stone-500 dark:text-stone-400">
              {isLoadingDirectory && !audioDirectory ? (
                <p>Checking current configuration…</p>
              ) : (
                <p>
                  Current value: <code>{audioDirectory?.audio_dir ?? "Not set"}</code>
                </p>
              )}
            </div>
          </form>
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
              Your data stays on this machine. Whombat does not send recordings
              or metadata to external servers.
            </p>
          </Info>
        </section>
      </div>
    </div>
  );
}
