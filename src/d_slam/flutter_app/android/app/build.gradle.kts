plugins { id("com.android.application"); id("kotlin-android"); id("dev.flutter.flutter-gradle-plugin") }
android { namespace="com.airescue.jetson"; compileSdk=flutter.compileSdkVersion; defaultConfig { applicationId="com.airescue.jetson"; minSdk=flutter.minSdkVersion; targetSdk=flutter.targetSdkVersion; versionCode=flutter.versionCode; versionName=flutter.versionName } }
flutter { source="../.." }
