package ru.yar.cyclecoach.core.database.di

import android.content.Context
import androidx.room.Room
import dagger.Module
import dagger.Provides
import dagger.hilt.InstallIn
import dagger.hilt.android.qualifiers.ApplicationContext
import dagger.hilt.components.SingletonComponent
import ru.yar.cyclecoach.core.database.CycleCoachDatabase
import javax.inject.Singleton

@Module
@InstallIn(SingletonComponent::class)
internal object DatabaseModule {

    @Provides
    @Singleton
    fun provideDatabase(@ApplicationContext context: Context): CycleCoachDatabase =
        Room.databaseBuilder(
            context,
            CycleCoachDatabase::class.java,
            "cyclecoach.db",
        ).build()
}
