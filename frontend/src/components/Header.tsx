import Link from 'next/link'

export default function Header() {
  return (
    <header className="bg-gray-800 text-white p-4">
      <nav className="container mx-auto flex justify-between items-center">
        <Link href="/" className="text-xl font-bold">
          Model Hub
        </Link>
        <div>
          <Link href="/model-catalog" className="mr-4">
            Model Catalog
          </Link>
          <Link href="/inference-endpoints">
            Inference Endpoints
          </Link>
        </div>
      </nav>
    </header>
  );
}