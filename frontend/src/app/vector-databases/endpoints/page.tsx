"use client";

import Header from "@/components/Header";
import Footer from "@/components/Footer";

export default function VectorDatabasesCatalog() {
  return (
    <div className="flex flex-col min-h-screen">
      <Header />
      <main className="flex-grow container mx-auto px-4 py-8">
        <h1 className="text-3xl font-bold mb-8">Vector Databases Endpoints</h1>
        <div className="text-center">
          <p className="mb-4">No datatabse endpoints available.</p>
        </div>
      </main>
      <Footer />
    </div>
  );
}
