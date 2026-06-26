import Logo from "../common/Logo";

export default function Navbar() {
  return (
    <nav className="flex items-center justify-between border-b bg-white px-8 py-4 shadow-sm">
      <Logo />

      <div className="flex items-center gap-4">
        <button className="rounded-lg border px-4 py-2 hover:bg-gray-100">
          English
        </button>

        <button className="rounded-lg border px-4 py-2 hover:bg-gray-100">
          العربية
        </button>

        <button className="rounded-lg bg-black px-4 py-2 text-white">
          Dark
        </button>
      </div>
    </nav>
  );
}