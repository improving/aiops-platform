import Link from 'next/link';
import Header from '@/components/Header';
import Footer from '@/components/Footer';

export default function Home() {
  return (
    <div className="flex flex-col min-h-screen">
      <Header />
      <main className="flex-grow container mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold mb-8">Welcome to Model Hub</h1>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          <Link href="/model-catalog" className="btn btn-primary">
            Model Catalog
          </Link>
          <Link href="/inference-endpoints" className="btn btn-secondary">
            Inference Endpoints
          </Link>
        </div>
      </main>
      <Footer />
    </div>
  );
}
