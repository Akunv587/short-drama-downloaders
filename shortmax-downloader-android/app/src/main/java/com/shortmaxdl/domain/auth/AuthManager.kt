package com.shortmaxdl.domain.auth

import android.util.Log
import com.shortmaxdl.data.http.PersistentCookieJar
import javax.inject.Inject
import javax.inject.Singleton

/**
 * Manages VIP login state via cookies.
 *
 * B2 strategy (primary): User logs in via embedded WebView,
 * cookies are captured and used for subsequent page requests.
 *
 * B1 strategy (fallback): Manual token/cookie paste.
 *
 * Base reference: TT/fsk-tool CDP cookie flow + TikTok lessons Cookie预检原则
 */
@Singleton
class AuthManager @Inject constructor(
    private val cookieJar: PersistentCookieJar,
) {
    companion object {
        private const val TAG = "AuthManager"
        const val SHORTMAX_DOMAIN = "shorttv.live"
        const val SHORTMAX_DOMAIN_ALT = "shortmax.com"
    }

    /** Whether we have stored cookies that look like a valid login session. */
    val isLoggedIn: Boolean
        get() {
            val cookies = cookieJar.getCookiesForDomain(SHORTMAX_DOMAIN) +
                cookieJar.getCookiesForDomain(SHORTMAX_DOMAIN_ALT)
            // Check for typical auth cookies (session token, user id, etc.)
            val hasAuthCookie = cookies.any { cookie ->
                cookie.name.lowercase() in setOf(
                    "token", "id_token", "access_token", "session",
                    "auth_token", "sid", "connect.sid", "ssid"
                ) || cookie.name.lowercase().contains("session") ||
                    cookie.name.lowercase().contains("auth") ||
                    cookie.name.lowercase().contains("token")
            }
            Log.d(TAG, "Login check: ${cookies.size} cookies, hasAuth=$hasAuthCookie")
            return cookies.isNotEmpty() && hasAuthCookie
        }

    /**
     * Get the full cookie string for HTTP requests.
     * Used to inject into ShortMaxParser page fetches.
     */
    fun getCookieString(): String {
        return cookieJar.getCookieString(SHORTMAX_DOMAIN)
            .ifEmpty { cookieJar.getCookieString(SHORTMAX_DOMAIN_ALT) }
    }

    /**
     * Persist cookies captured from WebView login.
     *
     * @param url  The URL the cookies came from
     * @param cookieString Raw cookie string (e.g. "name1=value1; name2=value2")
     */
    fun saveCookiesFromWebView(url: String, cookieString: String) {
        if (cookieString.isBlank()) return

        val domain = extractDomain(url)
        Log.d(TAG, "Saving cookies for domain=$domain: ${cookieString.take(100)}...")

        // Parse cookie string and add to persistent jar
        cookieString.split(";").forEach { pair ->
            val parts = pair.trim().split("=", limit = 2)
            if (parts.size == 2) {
                val cookie = okhttp3.Cookie.Builder()
                    .name(parts[0].trim())
                    .value(parts[1].trim())
                    .domain(domain)
                    .path("/")
                    .build()
                cookieJar.saveFromResponse(
                    okhttp3.HttpUrl.Builder()
                        .scheme("https")
                        .host(domain.removePrefix("."))
                        .build(),
                    listOf(cookie)
                )
            }
        }
        Log.i(TAG, "Saved cookies for $domain, loggedIn=$isLoggedIn")
    }

    /**
     * Clear all stored login cookies.
     */
    fun logout() {
        cookieJar.clear()
        Log.i(TAG, "Logged out, all cookies cleared")
    }

    private fun extractDomain(url: String): String {
        return try {
            val uri = java.net.URI(if (url.startsWith("http")) url else "https://$url")
            ".${uri.host?.removePrefix("www.") ?: SHORTMAX_DOMAIN}"
        } catch (_: Exception) {
            ".$SHORTMAX_DOMAIN"
        }
    }
}
