import NextAuth from "next-auth";
import Credentials from "next-auth/providers/credentials";

export const { handlers, auth } = NextAuth({
  providers: [
    Credentials({
      name: "Demo",
      credentials: { email: {}, password: {} },
      authorize(credentials) {
        if (!credentials?.email) return null;
        return { id: "demo-user", email: String(credentials.email) };
      }
    })
  ]
});
