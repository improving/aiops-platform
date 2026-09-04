"use client";

import React from 'react';
import { LANGFLOW_URL } from '@/constants';

export default function Develop() {
    return (
        <div className="flex justify-center items-center h-screen">
            <iframe
                src={LANGFLOW_URL}
                className="w-full h-full"
                title="Develop Environment"
                frameBorder="0"
                allowFullScreen
            />
        </div>
    );
}
