"use client";

import React from 'react';

export default function Develop() {
    return (
        <div className="flex justify-center items-center h-screen">
            <iframe
                src={ process.env.LANGFLOW_URL || "http://192.0.2.211:8080" }
                className="w-full h-full"
                title="Develop Environment"
                frameBorder="0"
                allowFullScreen
            />
        </div>
    );
}
