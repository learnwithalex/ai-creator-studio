import Link from "next/link";

export default function HomePage() {
  return (
    <main style={{ padding: 32 }}>
      <h1>AI Creator Studio</h1>
      <p>Real-time virtual camera with AI face swap.</p>
      <Link href="/studio">Open Studio</Link>
    </main>
  );
}
