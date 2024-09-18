"use client";

import { Suspense } from 'react';
import VectorDBEndpoints from '@/components/vector-databases/VectorDBEndpoints';
import { Skeleton } from '@/components/ui/skeleton';
import Header from "@/components/Header";
import Footer from "@/components/Footer";

export default function VectorDatabasesEndpoints() {
  return (
    <div className="flex flex-col min-h-screen">
      <Header />
      <main className="flex-grow container mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold mb-8">Vector Databases Endpoints</h1>
        <Suspense fallback={<Skeleton className="w-full h-[200px]" />}>
          <VectorDBEndpoints />
        </Suspense>
      </main>
      <Footer />
    </div>
  );
}
