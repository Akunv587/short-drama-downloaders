package com.shortmaxdl.domain.parser

import android.util.Log
import org.json.JSONArray
import org.json.JSONObject

/**
 * Port of zaizaimao/platforms/shortmax.py NuxtDataResolver.
 *
 * Nuxt __NUXT_DATA__ is a JSON array where integer values in dictionaries
 * are INDEX REFERENCES to other elements in the same array.
 * We recursively resolve these to get actual values.
 *
 * Base reference: zaizaimao/platforms/shortmax.py lines 58-123
 */
class NuxtDataResolver(private val data: JSONArray) {

    private val cache = mutableMapOf<Int, Any?>()
    private val resolving = mutableSetOf<Int>()

    companion object {
        private const val TAG = "NuxtDataResolver"
        private const val MAX_DEPTH = 20
    }

    /**
     * Resolve the value at [idx] in the data array, following index references.
     */
    fun resolve(idx: Int, maxDepth: Int = MAX_DEPTH): Any? {
        if (idx in cache) return cache[idx]
        if (idx in resolving) return null // Circular reference

        if (idx < 0 || idx >= data.length()) return null

        resolving.add(idx)
        try {
            val value = data.opt(idx)
            val result = resolveValue(value, maxDepth - 1)
            cache[idx] = result
            return result
        } finally {
            resolving.remove(idx)
        }
    }

    private fun resolveValue(value: Any?, depth: Int): Any? {
        if (depth <= 0) return value
        if (value == null || value == JSONObject.NULL) return null

        return when (value) {
            is Int -> {
                if (value in 0 until data.length()) {
                    resolve(value, depth) // Index reference → recurse
                } else {
                    value
                }
            }

            is JSONObject -> {
                val resolved = JSONObject()
                for (key in value.keys()) {
                    val v = value.opt(key)
                    resolved.put(key, resolveEntry(v, depth))
                }
                resolved
            }

            is JSONArray -> {
                // Handle Nuxt special markers: ["ShallowReactive", N]
                if (value.length() == 2) {
                    val first = value.opt(0)
                    if (first is String && first in setOf("ShallowReactive", "Reactive", "Set")) {
                        return value // Keep marker as-is
                    }
                }
                val resolved = JSONArray()
                for (i in 0 until value.length()) {
                    resolved.put(resolveEntry(value.opt(i), depth))
                }
                resolved
            }

            is String -> value
            is Boolean -> value
            is Double -> value
            is Long -> value
            else -> value
        }
    }

    private fun resolveEntry(value: Any?, depth: Int): Any? {
        // If integer and within array bounds, treat as index reference
        return when (value) {
            is Int -> {
                if (value in 0 until data.length()) {
                    resolve(value, depth)
                } else {
                    resolveValue(value, depth)
                }
            }

            else -> resolveValue(value, depth)
        }
    }

    /**
     * Find the shortPlay data object in the Nuxt data array.
     * Searches for a dictionary containing "shortPlayId" key.
     *
     * Base reference: zaizaimao/platforms/shortmax.py lines 112-123
     */
    fun findShortplayData(): JSONObject? {
        // First pass: look for raw object with shortPlayId
        for (i in 0 until data.length()) {
            val item = data.opt(i)
            if (item is JSONObject && item.has("shortPlayId")) {
                val resolved = resolveValue(item, MAX_DEPTH)
                if (resolved is JSONObject) {
                    Log.d(TAG, "Found shortPlayId in raw item at index $i")
                    return resolved
                }
            }
        }

        // Second pass: resolve everything and search
        for (i in 0 until data.length()) {
            val resolved = resolve(i)
            if (resolved is JSONObject && resolved.has("shortPlayId")) {
                Log.d(TAG, "Found shortPlayId via resolve at index $i")
                return resolved
            }
        }

        // Third pass: search nested structures
        for (i in 0 until data.length()) {
            val resolved = resolve(i)
            if (resolved is JSONObject) {
                val found = findShortPlayIdIn(resolved)
                if (found != null) return found
            } else if (resolved is JSONArray) {
                for (j in 0 until resolved.length()) {
                    val item = resolved.opt(j)
                    if (item is JSONObject) {
                        if (item.has("shortPlayId")) return item
                        val found = findShortPlayIdIn(item)
                        if (found != null) return found
                    }
                }
            }
        }

        return null
    }

    private fun findShortPlayIdIn(obj: JSONObject, maxDepth: Int = 5): JSONObject? {
        if (maxDepth <= 0) return null
        if (obj.has("shortPlayId")) return obj

        for (key in obj.keys()) {
            val value = obj.opt(key)
            when (value) {
                is JSONObject -> {
                    if (value.has("shortPlayId")) return value
                    findShortPlayIdIn(value, maxDepth - 1)?.let { return it }
                }

                is JSONArray -> {
                    for (i in 0 until minOf(value.length(), 20)) {
                        val item = value.opt(i)
                        if (item is JSONObject) {
                            if (item.has("shortPlayId")) return item
                            findShortPlayIdIn(item, maxDepth - 1)?.let { return it }
                        }
                    }
                }
            }
        }
        return null
    }
}
