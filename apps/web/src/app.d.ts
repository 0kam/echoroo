// See https://kit.svelte.dev/docs/types#app
// for information about these interfaces
import type { User } from '$lib/types';

declare global {
  namespace App {
    // interface Error {}
    interface Locals {
      isAuthenticated: boolean;
      user?: User;
    }
    // interface PageData {}
    // interface PageState {}
    // interface Platform {}
  }
}

export {};
