"use client";

import { Suspense } from 'react';
import VectorDBCatalog from '@/components/vector-databases/VectorDBCatalog';
import { Skeleton } from '@/components/ui/skeleton';
import Header from '@/components/Header';
import Footer from '@/components/Footer';

export default function VectorDBCatalogPage() {
  return (
    <div className="flex flex-col min-h-screen">
    <Header />
    <main className="flex-grow container mx-auto px-4 py-8">
      <h1 className="text-3xl font-bold mb-8">Vector Database Catalog</h1>
      <Suspense fallback={<Skeleton className="w-full h-[200px]" />}>
        <VectorDBCatalog />
      </Suspense>
    </main>
    <Footer />
  </div>
  );
}
