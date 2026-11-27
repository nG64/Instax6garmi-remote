plugins {
    id("com.android.application")
}

// Die fertige Schluesselausgabe.html (eine Ebene über dem Android-Projekt) wird als App-Inhalt übernommen.
val htmlAssets = layout.buildDirectory.dir("generated/html-assets")
val kopiereHtml by tasks.registering(Copy::class) {
    from(rootProject.file("../Schluesselausgabe.html"))
    into(htmlAssets)
    rename { "index.html" }
}

android {
    namespace = "de.schluesselausgabe.app"
    compileSdk = 35

    defaultConfig {
        applicationId = "de.schluesselausgabe.app"
        minSdk = 29          // Android 10
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
    }

    // Fester Schlüssel, damit spätere Versionen über die alte App installiert werden können
    // (sonst gehen die im Tablet gespeicherten Unterschriften beim Neuinstallieren verloren).
    signingConfigs {
        create("intern") {
            storeFile = file("schluessel.keystore")
            storePassword = "schluesselausgabe"
            keyAlias = "schluesselausgabe"
            keyPassword = "schluesselausgabe"
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            signingConfig = signingConfigs.getByName("intern")
        }
        debug {
            signingConfig = signingConfigs.getByName("intern")
        }
    }

    sourceSets["main"].assets.srcDir(htmlAssets)

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

tasks.named("preBuild") { dependsOn(kopiereHtml) }

dependencies {
    implementation("androidx.webkit:webkit:1.12.1")
}
