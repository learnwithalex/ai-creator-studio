export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body style={{ margin: 0, fontFamily: "Segoe UI, sans-serif", background: "#0f1115", color: "#f6f6f6" }}>{children}</body>
    </html>
  );
}
