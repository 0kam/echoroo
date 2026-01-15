import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation } from "@tanstack/react-query";
import type { AxiosError } from "axios";
import { useCallback } from "react";
import { useForm } from "react-hook-form";

import api from "@/app/api";

import { Checkbox, Group, Input } from "@/lib/components/inputs";
import Button from "@/lib/components/ui/Button";

import { UserCreateSchema } from "@/lib/schemas";
import type { UserCreate } from "@/lib/types";

export default function AdminUserCreateForm(props: {
  onCreate?: () => void;
}) {
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors },
  } = useForm<UserCreate>({
    resolver: zodResolver(UserCreateSchema),
    mode: "onBlur",
    defaultValues: {
      is_superuser: false,
    },
  });

  const { mutateAsync: createUser } = useMutation<unknown, AxiosError, UserCreate>(
    {
      mutationFn: api.adminUsers.create,
    },
  );

  const { onCreate } = props;

  const onSubmit = useCallback(
    async (data: UserCreate) => {
      await createUser(data);
      onCreate?.();
      reset({
        username: "",
        name: "",
        email: "",
        password: "",
        password_confirm: "",
        is_superuser: false,
      });
    },
    [createUser, onCreate, reset],
  );

  return (
    <form className="flex flex-col gap-2" onSubmit={handleSubmit(onSubmit)}>
      <Group label="Username" name="username" error={errors.username?.message}>
        <Input {...register("username")} />
      </Group>
      <Group label="Name" name="name" error={errors.name?.message}>
        <Input {...register("name")} />
      </Group>
      <Group label="Email" name="email" error={errors.email?.message}>
        <Input type="email" {...register("email")} />
      </Group>
      <div className="grid grid-cols-2 gap-2">
        <Group
          label="Password"
          name="password"
          error={errors.password?.message}
        >
          <Input type="password" autoComplete="new-password" {...register("password")} />
        </Group>
        <Group
          label="Confirm password"
          name="password_confirm"
          error={errors.password_confirm?.message}
        >
          <Input
            type="password"
            autoComplete="new-password"
            {...register("password_confirm")}
          />
        </Group>
      </div>
      <label className="flex items-center gap-2 text-sm text-stone-600 dark:text-stone-300">
        <Checkbox {...register("is_superuser")} />
        Grant administrator privileges
      </label>
      <div className="flex justify-end">
        <Button type="submit" variant="primary">
          Create user
        </Button>
      </div>
    </form>
  );
}
