package com.shortmaxdl.data.http

import okhttp3.Cookie
import okhttp3.CookieJar
import okhttp3.HttpUrl
import okhttp3.OkHttpClient
import okhttp3.logging.HttpLoggingInterceptor
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit

/**
 * Persistent CookieJar backed by in-memory storage.
 * Cookies survive across OkHttpClient instances.
 */
class PersistentCookieJar : CookieJar {

    private val cookieStore = ConcurrentHashMap<String, MutableList<Cookie>>()

    override fun saveFromResponse(url: HttpUrl, cookies: List<Cookie>) {
        val key = url.host
        cookieStore.getOrPut(key) { mutableListOf() }.let { stored ->
            // Replace existing cookies with same name
            cookies.forEach { newCookie ->
                stored.removeAll { it.name == newCookie.name }
                stored.add(newCookie)
            }
        }
    }

    override fun loadForRequest(url: HttpUrl): List<Cookie> {
        val host = url.host
        val allCookies = mutableListOf<Cookie>()

        // Exact host match
        cookieStore[host]?.let { allCookies.addAll(it) }

        // Domain match (e.g., .shorttv.live should match www.shorttv.live)
        cookieStore.forEach { (domain, cookies) ->
            if (host.endsWith(domain.removePrefix("."))) {
                cookies.forEach { cookie ->
                    if (allCookies.none { it.name == cookie.name }) {
                        allCookies.add(cookie)
                    }
                }
            }
        }

        return allCookies
    }

    /** Get all stored cookies for a domain. */
    fun getCookiesForDomain(domain: String): List<Cookie> {
        return cookieStore.entries
            .filter { (key, _) -> domain.contains(key) || key.contains(domain) }
            .flatMap { it.value }
    }

    /** Get cookies as a semicolon-separated string (for WebView injection). */
    fun getCookieString(domain: String): String {
        return getCookiesForDomain(domain).joinToString("; ") { "${it.name}=${it.value}" }
    }

    /** Clear all cookies. */
    fun clear() {
        cookieStore.clear()
    }
}

/**
 * Factory for creating OkHttpClient instances.
 * Provides anti-detection headers and cookie persistence.
 *
 * Base reference: zaizaimao/core/client.py
 */
object HttpClientFactory {

    // Anti-detection headers — use mobile UA on Android
    // Base reference: zaizaimao/core/client.py lines 12-28
    val DEFAULT_HEADERS = mapOf(
        "User-Agent" to (
            "Mozilla/5.0 (Linux; Android 14; Pixel 8) " +
                "AppleWebKit/537.36 (KHTML, like Gecko) " +
                "Chrome/126.0.0.0 Mobile Safari/537.36"
            ),
        "Accept" to "application/json, text/plain, */*",
        "Accept-Language" to "zh-CN,zh;q=0.9,en;q=0.8",
        "Sec-Ch-Ua" to "\"Not/A)Brand\";v=\"99\", \"Google Chrome\";v=\"126\", \"Chromium\";v=\"126\"",
        "Sec-Ch-Ua-Mobile" to "?1",
        "Sec-Ch-Ua-Platform" to "\"Android\"",
        "Sec-Fetch-Dest" to "empty",
        "Sec-Fetch-Mode" to "cors",
        "Sec-Fetch-Site" to "same-site",
    )

    /**
     * Create a standard HTTP client with cookie persistence.
     */
    fun create(cookieJar: CookieJar = PersistentCookieJar()): OkHttpClient {
        return OkHttpClient.Builder()
            .cookieJar(cookieJar)
            .connectTimeout(30, TimeUnit.SECONDS)
            .readTimeout(60, TimeUnit.SECONDS)
            .writeTimeout(60, TimeUnit.SECONDS)
            .followRedirects(true)
            .followSslRedirects(true)
            .addInterceptor { chain ->
                val builder = chain.request().newBuilder()
                DEFAULT_HEADERS.forEach { (k, v) -> builder.addHeader(k, v) }
                chain.proceed(builder.build())
            }
            .addInterceptor(
                HttpLoggingInterceptor().apply {
                    level = HttpLoggingInterceptor.Level.BODY
                }
            )
            .build()
    }
}
